/* Keep each Kratos session in its own tab; never replace an unrelated draft. */
async function kratosConversationTab(work) {
  const key = work.conversation?.key;
  if (typeof key !== "string" || !/^[a-f0-9]{32,64}$/.test(key)) throw new Error("Invalid conversation key");
  const provider = work.provider || "chatgpt-web";
  const config = KRATOS_BROWSER.providers[provider];
  if (!config) throw new Error("Unsupported browser provider");
  const name = "conversation-" + key;
  const existing = (await chrome.storage.local.get(name))[name];
  if (!work.conversation.new && existing?.provider === provider) {
    const tab = await chrome.tabs.get(existing.tab_id).catch(() => null);
    if (tab && chatgptUrl(tab.url, provider) && new URL(tab.url).pathname === new URL(existing.url).pathname) {
      return { tab_id: tab.id, url: tab.url, reset: false };
    }
    // A user navigation or closed tab loses provider context. The caller must
    // bootstrap its working context into a new tab, never send only a delta.
    return { reset: true };
  }
  if (!work.conversation.new) return { reset: true };
  const seed = await authorizedTab(null, provider).catch(() => null);
  const tab = await chrome.tabs.create({ url: config.url, active: false, ...(seed ? { windowId: seed.windowId } : {}) });
  const deadline = Date.now() + 30000;
  let loaded;
  do {
    loaded = await chrome.tabs.get(tab.id);
    if (loaded.status === "complete" && chatgptUrl(loaded.url, provider)) break;
    await new Promise(resolve => setTimeout(resolve, 200));
  } while (Date.now() < deadline);
  if (!loaded || loaded.status !== "complete" || !chatgptUrl(loaded.url, provider)) {
    const error = new Error("Provider page did not load"); error.code = "browser_tab_missing"; throw error;
  }
  await chrome.storage.local.set({ [name]: { tab_id: tab.id, url: loaded.url, provider } });
  return { tab_id: tab.id, url: loaded.url, reset: false };
}

async function kratosRememberConversation(work, tab) {
  if (!work.conversation?.key) return;
  const current = await chrome.tabs.get(tab.id);
  await chrome.storage.local.set({ ["conversation-" + work.conversation.key]: {
    tab_id: tab.id, url: current.url, provider: tab.provider,
  } });
}

if (typeof module !== "undefined") module.exports = { kratosConversationTab, kratosRememberConversation };
