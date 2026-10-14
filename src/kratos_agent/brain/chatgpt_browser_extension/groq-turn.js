async function groqNativeTurn(tab, work) {
  if (tab.provider !== "groq-web" || typeof work.prompt !== "string" || !work.prompt.trim())
    throw chatgptTurnError("browser_submit_unavailable");
  await chrome.debugger.sendCommand({ tabId: tab.id }, "Network.enable", { maxPostDataSize: 4 * 1024 * 1024 });
  let requestId = null, submitted = false, finish, fail;
  const completed = new Promise((resolve, reject) => { finish = resolve; fail = reject; });
  completed.catch(() => {});
  const onEvent = (source, method, params) => {
    if (source.tabId !== tab.id) return;
    if (submitted && method === "Network.requestWillBeSent" && params.request?.method === "POST" && params.request.postData) {
      try {
        const url = new URL(params.request.url);
        if (url.origin !== "https://chat.groq.com") return;
        const body = JSON.parse(params.request.postData);
        const contains = value => typeof value === "string" ? value === work.prompt :
          Array.isArray(value) ? value.some(contains) : value && typeof value === "object" && Object.values(value).some(contains);
        if (contains(body)) requestId = params.requestId;
      } catch { /* Other page requests are unrelated to this prompt. */ }
    }
    if (params.requestId !== requestId || requestId === null) return;
    if (method === "Network.responseReceived" && (params.response.status < 200 || params.response.status >= 300))
      fail(chatgptTurnError("browser_response_incomplete", "http"));
    if (method === "Network.loadingFailed") fail(chatgptTurnError("browser_response_incomplete", "network"));
    if (method === "Network.loadingFinished") {
      void chrome.debugger.sendCommand({ tabId: tab.id }, "Network.getResponseBody", { requestId })
        .then(result => finish(result), () => fail(chatgptTurnError("browser_response_incomplete", "body")));
    }
  };
  chrome.debugger.onEvent.addListener(onEvent);
  const timer = setTimeout(() => fail(chatgptTurnError("browser_response_incomplete", "timeout")), 120000);
  cancelGroq = () => fail(chatgptTurnError("browser_response_incomplete"));
  try {
    const ready = await evaluate(tab, `(() => {
      const visible = selector => [...document.querySelectorAll(selector)].find(node => node.getClientRects().length);
      const input = visible('#chat, textarea, [contenteditable="true"][role="textbox"]');
      if (!input) return {error:'browser_submit_unavailable'};
      if ((input.value || input.innerText || '').trim()) return {error:'browser_draft_present'};
      if (visible('button[aria-label="stop"], button[aria-label="Stop"]')) return {error:'browser_page_busy'};
      input.focus(); return {ready:true};
    })()`);
    if (!ready?.ready) throw chatgptTurnError(ready?.error || "browser_submit_unavailable");
    await chrome.debugger.sendCommand({ tabId: tab.id }, "Input.insertText", { text: work.prompt });
    await new Promise(resolve => setTimeout(resolve, 200));
    submitted = true;
    const sent = await evaluate(tab, `(() => {
      const button = [...document.querySelectorAll('button[aria-label="send"], button[aria-label="Send"], button[aria-label="Send message"], button[type="submit"]')].find(node => node.getClientRects().length && !node.disabled);
      if (!button) return false; button.click(); return true;
    })()`);
    if (!sent) throw chatgptTurnError("browser_submit_unavailable");
    const result = await completed;
    if (typeof result?.body !== "string" || result.base64Encoded || result.body.length > 16 * 1024 * 1024)
      throw chatgptTurnError("browser_response_incomplete", "body");
    return { body: result.body };
  } finally {
    clearTimeout(timer);
    chrome.debugger.onEvent.removeListener(onEvent);
    cancelGroq = null;
  }
}
