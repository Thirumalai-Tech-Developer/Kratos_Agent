// Credential collection only. OmniRoute owns all model execution.
importScripts("config.js");
let busy = false;
const refreshTimers = new Map();
function chatgptUrl(value, provider = null) {
  try {
    return Object.entries(KRATOS_BROWSER.providers).some(
      ([id, c]) =>
        (!provider || id === provider) &&
        new URL(value).origin === new URL(c.url).origin,
    );
  } catch {
    return false;
  }
}
async function collectSnapshot(provider, requestedStore = null) {
  const config = KRATOS_BROWSER.providers[provider];
  if (!config) throw new Error("Unsupported browser provider");
  const origin = new URL(config.url).origin;
  const tabs = await chrome.tabs.query({ url: origin + "/*" });
  const stores = await chrome.cookies.getAllCookieStores();
  const store =
    requestedStore === null
      ? stores.find((s) => tabs.some((t) => s.tabIds.includes(t.id))) ||
        stores.find((s) => s.id === "0") ||
        stores[0]
      : stores.find((s) => s.id === requestedStore);
  if (!store) throw new Error("Browser cookie store unavailable");
  const tab = tabs.find((t) => store.tabIds.includes(t.id));
  let storage;
  if (tab) {
    try {
      storage = await chrome.tabs.sendMessage(tab.id, {
        kind: "kratos-storage-snapshot",
      });
      if (
        storage?.origin !== origin ||
        !chatgptUrl((await chrome.tabs.get(tab.id)).url, provider)
      )
        storage = null;
    } catch {
      /* Cookies work when the content script is unavailable. */
    }
  }
  const cookies = new Map();
  for (const domain of config.domains) {
    for (const c of await chrome.cookies.getAll({
      domain,
      storeId: store.id,
    })) {
      const host = c.domain.toLowerCase().replace(/^\./, "");
      if (!config.domains.some((d) => host === d || host.endsWith("." + d)))
        continue;
      if (
        provider === "gemini-web" &&
        !["__Secure-1PSID", "__Secure-1PSIDTS", "__Secure-1PSIDCC"].includes(
          c.name,
        )
      )
        continue;
      cookies.set(
        JSON.stringify([c.name, c.domain, c.path, c.partitionKey || null]),
        {
          name: c.name,
          value: c.value,
          domain: c.domain,
          path: c.path,
          expires: c.expirationDate ?? -1,
          httpOnly: c.httpOnly,
          secure: c.secure,
          sameSite:
            {
              strict: "Strict",
              lax: "Lax",
              no_restriction: "None",
              unspecified: "Lax",
            }[c.sameSite] || "Lax",
        },
      );
    }
  }
  return {
    url: config.url,
    cookie_store_id: store.id,
    user_agent: navigator.userAgent,
    storage_state: {
      cookies: [...cookies.values()],
      origins: storage ? [storage] : [],
    },
  };
}
async function handleWork(work) {
  if (work.action === "release") return { released: true };
  if (work.action !== "inspect")
    throw new Error("Unsupported cookie collector command");
  return collectSnapshot(
    work.provider || "chatgpt-web",
    work.cookie_store_id ?? null,
  );
}
async function localRequest(base, path, data) {
  const response = await fetch(base + path, {
    method: data === undefined ? "GET" : "POST",
    cache: "no-store",
    headers: {
      Authorization: "Bearer " + KRATOS_BROWSER.token,
      "Content-Type": "application/json",
    },
    ...(data === undefined ? {} : { body: JSON.stringify(data) }),
    signal: AbortSignal.timeout(5000),
  });
  const result = await response.json();
  if (!response.ok)
    throw new Error(result.error || "Kratos cookie receiver unavailable");
  return result;
}
async function panelRequest(action, data) {
  const result = await localRequest(
    KRATOS_BROWSER.control,
    "/" + action,
    action === "status" ? undefined : data || {},
  );
  if (action === "status") {
    const connected = result.accounts.some((a) => a.connected && a.gateway_sync?.synced && a.gateway_sync?.enabled);
    const error = result.error || result.accounts.some((a) => a.gateway_sync?.error);
    await chrome.action.setBadgeText({
      text: error ? "!" : result.busy ? "…" : connected ? "✓" : "",
    });
    await chrome.action.setBadgeBackgroundColor({
      color: error ? "#ef4444" : connected ? "#16a34a" : "#64748b",
    });
  }
  return result;
}
async function poll() {
  if (busy) return;
  busy = true;
  try {
    const work = await localRequest(KRATOS_BROWSER.endpoint, "/work");
    if (!work.id) return;
    let result, error;
    try {
      result = await handleWork(work);
    } catch {
      error = "browser_operation_failed";
    }
    await localRequest(KRATOS_BROWSER.endpoint, "/result", {
      id: work.id,
      result,
      error,
    });
  } catch {
    /* Model requests use saved credentials independently. */
  } finally {
    busy = false;
  }
}
async function refreshBound(provider) {
  const status = await panelRequest("status");
  const stores = new Set(
    status.accounts
      .filter((a) => a.provider === provider && a.auto_refresh)
      .map((a) => a.cookie_store_id),
  );
  for (const store of stores)
    if (typeof store === "string")
      await panelRequest("sync", {
        provider,
        snapshot: await collectSnapshot(provider, store),
      });
}
function scheduleRefresh(provider) {
  clearTimeout(refreshTimers.get(provider));
  refreshTimers.set(
    provider,
    setTimeout(() => {
      refreshTimers.delete(provider);
      void refreshBound(provider).catch(() => {});
    }, 1500),
  );
}
chrome.cookies.onChanged.addListener(({ cookie }) => {
  const host = cookie.domain.toLowerCase().replace(/^\./, "");
  for (const [provider, c] of Object.entries(KRATOS_BROWSER.providers))
    if (c.domains.some((d) => host === d || host.endsWith("." + d)))
      scheduleRefresh(provider);
});
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (message?.kind === "kratos-chatgpt-poll" && chatgptUrl(sender.tab?.url)) {
    void poll().then(() => reply({ ok: true }));
    return true;
  }
  if (
    sender.url !== chrome.runtime.getURL("popup.html") ||
    message?.kind !== "kratos-panel"
  )
    return;
  if (
    !["status", "connect", "select", "disconnect", "models", "sync_service"].includes(
      message.action,
    )
  )
    return;
  void (async () => {
    void poll();
    let data = message.data || {};
    if (message.action === "connect")
      data = {
        ...data,
        snapshot: await collectSnapshot(data.provider || "chatgpt-web"),
      };
    if (message.action === "models") {
      const status = await panelRequest("status");
      const a = status.accounts.find((a) => a.id === data.account_id);
      if (a?.auto_refresh)
        await panelRequest("sync", {
          provider: a.provider,
          snapshot: await collectSnapshot(a.provider, a.cookie_store_id),
        });
    }
    return panelRequest(message.action, data);
  })().then(reply, async () => {
    await chrome.action.setBadgeText({ text: "!" });
    await chrome.action.setBadgeBackgroundColor({ color: "#ef4444" });
    reply({
      error:
        "Cookie collection failed. Keep Kratos Studio running and sign in normally on the website if the session expired.",
    });
  });
  return true;
});
if (chrome.alarms) {
  chrome.alarms.create("kratos-cookie-refresh", { periodInMinutes: 1 });
  chrome.alarms.onAlarm.addListener(() => {
    void poll();
    void panelRequest("status")
      .then((s) =>
        Promise.allSettled(
          [
            ...new Set(
              s.accounts.filter((a) => a.auto_refresh).map((a) => a.provider),
            ),
          ].map(refreshBound),
        ),
      )
      .catch(() => {});
  });
  setInterval(() => void poll(), 1000);
  void poll();
}
