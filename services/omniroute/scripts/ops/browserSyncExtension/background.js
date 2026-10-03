/* Uses the user's original Chrome profile; never opens a replacement browser. */
importScripts("config.js");
let busy = false;

function tabMatchesProvider(tab, provider) {
  try {
    return new URL(tab.url).origin === new URL(provider.homeUrl).origin;
  } catch {
    return false;
  }
}

function cookieMatchesProvider(cookie, provider) {
  const actual = String(cookie?.domain || "")
    .replace(/^\./, "")
    .toLowerCase();
  const expected = provider.domain.replace(/^\./, "").toLowerCase();
  return actual === expected || actual.endsWith("." + expected);
}

function missingCredentialDetail(provider) {
  if (provider.id === "muse-spark-web")
    return provider.id + ": open its signed-in tab; websocket companion token required";
  if (
    provider.sources.some((source) =>
      ["localStorage", "sessionStorage", "header"].includes(source.type)
    )
  )
    return provider.id + ": open its signed-in tab; token or required session cookie missing";
  return provider.id + ": sign-in or required session cookie missing";
}

async function readTabSnapshot(tab, provider, authIdentity) {
  const message = {
    type: "capture",
    provider: provider.id,
    sources: provider.sources,
    authIdentity,
  };
  try {
    return await chrome.tabs.sendMessage(tab.id, message);
  } catch {
    // Old tabs can lack the content script after installation or an extension reload.
    try {
      await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        files: ["modelDiscovery.js", "content.js"],
      });
      await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        files: ["modelObserver.js"],
        world: "MAIN",
      });
      return await chrome.tabs.sendMessage(tab.id, message);
    } catch {
      return undefined;
    }
  }
}

async function capture(provider, tabs) {
  try {
    // Cookie sessions belong to this Chrome profile and remain accessible with tabs closed.
    const cookies = (
      await chrome.cookies.getAll({ domain: provider.domain.replace(/^\./, "") })
    ).map((cookie) => ({
      name: cookie.name,
      value: cookie.value,
      domain: cookie.domain,
      path: cookie.path,
      expires: cookie.expirationDate ?? -1,
    }));
    const cookieIdentity = JSON.stringify(
      cookies.map((cookie) => [cookie.name, cookie.value]).sort()
    );
    const authBytes = await crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(cookieIdentity)
    );
    const authIdentity = Array.from(new Uint8Array(authBytes), (byte) =>
      byte.toString(16).padStart(2, "0")
    ).join("");
    let snapshot = { storage: {}, userAgent: navigator.userAgent };
    const providerTabs = tabs
      .filter((candidate) => tabMatchesProvider(candidate, provider))
      .sort(
        (left, right) =>
          Number(right.active || false) - Number(left.active || false) ||
          (right.lastAccessed || 0) - (left.lastAccessed || 0)
      );
    for (const tab of providerTabs) {
      const observed = await readTabSnapshot(tab, provider, authIdentity);
      if (!observed) continue;
      snapshot = {
        storage: observed.storage || {},
        userAgent: observed.userAgent || navigator.userAgent,
        ...(typeof observed.authorization === "string"
          ? { authorization: observed.authorization }
          : {}),
        ...(Array.isArray(observed.models) ? { models: observed.models } : {}),
      };
      break;
    }
    if (
      provider.id === "muse-spark-web" &&
      !snapshot.authorization?.startsWith("ecto1:") &&
      !Array.isArray(snapshot.models)
    )
      return { status: "waiting", detail: missingCredentialDetail(provider) };
    if (
      !cookies.length &&
      !Object.values(snapshot.storage).some(Boolean) &&
      !snapshot.authorization &&
      !Array.isArray(snapshot.models)
    )
      return { status: "waiting", detail: missingCredentialDetail(provider) };
    const response = await fetch(SYNC_CONFIG.endpoint + "/sync", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + SYNC_CONFIG.token,
      },
      body: JSON.stringify({ provider: provider.id, snapshot: { ...snapshot, cookies } }),
      signal: AbortSignal.timeout(15000),
      redirect: "error",
    });
    if (response.status === 202)
      return { status: "waiting", detail: missingCredentialDetail(provider) };
    if (response.ok) return { status: "synced" };
    if (response.status === 422)
      return { status: "waiting", detail: missingCredentialDetail(provider) };
    return {
      status: "unavailable",
      detail: provider.id + ": local sync unavailable (" + response.status + ")",
    };
  } catch {
    return {
      status: "unavailable",
      detail: provider.id + ": local sync unavailable; start Studio or check browser access",
    };
  }
}

async function scan() {
  if (busy) return;
  busy = true;
  try {
    const tabs = await chrome.tabs.query({}).catch(() => []);
    const results = [];
    for (const provider of SYNC_CONFIG.providers) results.push(await capture(provider, tabs));
    const synced = results.filter((result) => result.status === "synced").length;
    const issues = results.filter((result) => result.status !== "synced");
    await chrome.action.setBadgeText({
      text: !synced ? "0" : issues.length ? "!" : String(synced),
    });
    await chrome.action.setTitle({
      title:
        "Kratos: " +
        synced +
        "/" +
        results.length +
        " provider sessions synced" +
        (issues.length
          ? "; " +
            issues
              .slice(0, 3)
              .map((result) => result.detail)
              .join("; ")
          : ""),
    });
  } finally {
    busy = false;
  }
}

chrome.runtime.onInstalled.addListener(async () => {
  // No website reloads: existing chats remain in place. Inject observation into current tabs.
  for (const tab of await chrome.tabs.query({})) {
    try {
      const provider = SYNC_CONFIG.providers.find((candidate) =>
        tabMatchesProvider(tab, candidate)
      );
      if (!provider) continue;
      await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        files: ["modelDiscovery.js", "content.js"],
      });
      await chrome.scripting.executeScript({
        target: { tabId: tab.id }, files: ["modelObserver.js"], world: "MAIN",
      });
      if (provider.id === "muse-spark-web")
        await chrome.scripting.executeScript({
          target: { tabId: tab.id },
          files: ["metaObserver.js"],
          world: "MAIN",
        });
    } catch {
      /* Restricted pages are deliberately ignored. */
    }
  }
  await chrome.alarms.create("sync", { periodInMinutes: 0.5 });
  await scan();
});
chrome.runtime.onStartup.addListener(async () => {
  await chrome.alarms.create("sync", { periodInMinutes: 0.5 });
  await scan();
});
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "sync") void scan();
});
chrome.tabs.onUpdated.addListener((_id, change) => {
  if (change.status === "complete") void scan();
});
let changedTimer;
chrome.cookies.onChanged.addListener((change) => {
  if (!SYNC_CONFIG.providers.some((provider) => cookieMatchesProvider(change.cookie, provider)))
    return;
  clearTimeout(changedTimer);
  changedTimer = setTimeout(() => void scan(), 1500);
});
chrome.action.onClicked.addListener(() => void scan());
