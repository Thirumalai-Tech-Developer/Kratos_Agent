const accountList = document.getElementById("accounts");
const statusText = document.getElementById("status");
const notice = document.getElementById("notice");
let working = false;
let latest = null;

async function send(action, data) {
  const result = await chrome.runtime.sendMessage({
    kind: "kratos-panel",
    action,
    data,
  });
  if (!result || (result.error && !(action === "status" && result.ready)))
    throw new Error(result?.error || "Connection panel unavailable");
  return result;
}

function showNotice(message, error = false) {
  notice.textContent = message || "";
  notice.hidden = !message;
  notice.classList.toggle("error", error);
}

function button(label, action, data, className = "quiet") {
  const element = document.createElement("button");
  element.textContent = label;
  element.className = className;
  element.disabled = working;
  element.addEventListener("click", () =>
    perform(action, typeof data === "function" ? data() : data),
  );
  return element;
}

function render(state) {
  working = state.busy;
  document.getElementById("connect").disabled = working;
  const connected = state.accounts.filter((account) => account.connected);
  statusText.textContent = working
    ? "Checking the saved website session…"
    : connected.length
      ? `${connected.length} connected login${connected.length > 1 ? "s" : ""}`
      : "No accounts connected";
  statusText.classList.toggle(
    "connected",
    connected.length > 0 && !working && !state.error,
  );
  showNotice(state.error || state.message, Boolean(state.error));
  const snapshot = JSON.stringify([state.accounts, state.busy]);
  if (latest === snapshot) return; // Preserve a model selection while status is polled.
  latest = snapshot;
  accountList.replaceChildren();
  if (!state.accounts.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Your connected accounts will appear here.";
    accountList.append(empty);
  }
  for (const account of state.accounts) {
    const card = document.createElement("article");
    card.className = "account";
    const name = document.createElement("p");
    name.className = "account-name";
    name.textContent =
      (account.provider_name || "ChatGPT") +
      (account.email ? " · " + account.email : " account");
    const tag = document.createElement("span");
    tag.className =
      "tag " +
      (account.error || account.session_expired
        ? "error"
        : account.connected
          ? "connected"
          : "disconnected");
    tag.textContent = account.session_expired
      ? "Session expired"
      : account.error
        ? "Connection error"
        : account.connected
          ? "Cookies collected"
          : "Disconnected";
    card.append(name, tag);
    const sync = account.gateway_sync || {};
    const service = document.createElement("p");
    service.className = "tag " + (sync.synced && sync.enabled ? "connected" : sync.error ? "error" : "disconnected");
    service.textContent = sync.synced
      ? (sync.enabled ? "OmniRoute synced" : "OmniRoute connection disabled")
      : sync.error || "Waiting to sync cookies to OmniRoute";
    card.append(service);
    if (sync.usage === "native_codex_only") {
      const scope = document.createElement("p");
      scope.className = "empty";
      scope.textContent = "OmniRoute ChatGPT connection supports native Codex requests. Kratos chat uses its local browser executor.";
      card.append(scope);
    }
    if (sync.pending || !sync.synced) card.append(button("Retry OmniRoute sync", "sync_service", { account_id: account.id }));
    if (account.active) {
      const active = document.createElement("span");
      active.className = "active-label";
      active.textContent = "Active in Kratos";
      card.append(active);
    }
    if (account.connected) {
      const label = document.createElement("label");
      label.className = "model-label";
      label.textContent = "Model";
      const select = document.createElement("select");
      select.id = "model-" + account.id;
      label.htmlFor = select.id;
      select.disabled = working || !account.models.length;
      if (!account.models.length) {
        const option = document.createElement("option");
        option.textContent = "No supported models found";
        select.append(option);
      }
      for (const model of account.models) {
        const option = document.createElement("option");
        option.value = model.id;
        option.textContent = model.display_name;
        select.append(option);
      }
      if (account.models.some((model) => model.id === account.model))
        select.value = account.model;
      const effortLabel = document.createElement("label");
      effortLabel.className = "model-label";
      effortLabel.textContent = "Thinking capacity";
      const effort = document.createElement("select");
      effort.id = "effort-" + account.id;
      effortLabel.htmlFor = effort.id;
      const updateEffort = () => {
        const model = account.models.find((item) => item.id === select.value);
        const tiers = model?.effort_tiers || [];
        effort.replaceChildren();
        const defaultOption = document.createElement("option");
        defaultOption.value = "";
        defaultOption.textContent = tiers.length
          ? "Provider default"
          : model?.supports_reasoning
            ? "Thinking fixed by model"
            : "Thinking control unavailable";
        effort.append(defaultOption);
        for (const tier of tiers) {
          const option = document.createElement("option");
          option.value = tier;
          option.textContent =
            {
              low: "Low",
              medium: "Medium",
              high: "High",
              xhigh: "Extra high",
              max: "Maximum",
            }[tier] || tier;
          effort.append(option);
        }
        effort.disabled = working || !tiers.length;
        if (
          select.value === account.model &&
          tiers.includes(account.reasoning_effort)
        )
          effort.value = account.reasoning_effort;
      };
      select.addEventListener("change", updateEffort);
      updateEffort();
      const actions = document.createElement("div");
      actions.className = "actions";
      const use = button(
        "Use model",
        "select",
        () => ({
          account_id: account.id,
          model: select.value,
          reasoning_effort: effort.value || null,
        }),
        "",
      );
      use.disabled ||= !account.models.length;
      actions.append(
        use,
        button("Check login", "models", { account_id: account.id }),
        button(
          "Disconnect",
          "disconnect",
          { account_id: account.id },
          "danger",
        ),
      );
      card.append(label, select, effortLabel, effort, actions);
    } else {
      card.append(
        button("Reconnect", "connect", {
          provider: account.provider || "chatgpt-web",
        }),
      );
    }
    accountList.append(card);
  }
}

async function refresh() {
  try {
    render(await send("status"));
  } catch (error) {
    latest = null;
    working = false;
    document.getElementById("connect").disabled = true;
    statusText.textContent = "Connection unavailable";
    statusText.classList.remove("connected");
    showNotice(error.message, true);
    for (const control of accountList.querySelectorAll("button, select"))
      control.disabled = true;
  }
}

async function perform(action, data) {
  if (working) return;
  working = true;
  document.getElementById("connect").disabled = working;
  showNotice(
    action === "connect"
      ? "Collecting session cookies and validating the login…"
      : "Updating connection…",
  );
  try {
    await send(action, data);
    await refresh();
  } catch (error) {
    working = false;
    document.getElementById("connect").disabled = false;
    showNotice(error.message, true);
  }
}

document
  .getElementById("connect")
  .addEventListener("click", () =>
    perform("connect", { provider: document.getElementById("provider").value }),
  );
document.getElementById("refresh").addEventListener("click", refresh);
void refresh();
setInterval(refresh, 1500);
