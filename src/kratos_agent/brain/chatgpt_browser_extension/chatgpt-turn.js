// Let the signed-in website submit the turn and own its authentication/challenges.
// Only a fresh, completed assistant turn is eligible to leave this transport.
function chatgptTurnError(code, reason = '') {
  const error = new Error(code);
  error.code = code;
  error.reason = reason;
  return error;
}

async function chatgptComposerSelection(selection) {
  const visible = selector => [...document.querySelectorAll(selector)].find(node => node.getClientRects().length);
  const composerDeadline = Date.now() + 15000;
  let input;
  do {
    input = visible('#prompt-textarea, [contenteditable="true"][role="textbox"], [contenteditable="true"].ProseMirror');
    if (input) break;
    await new Promise(resolve => setTimeout(resolve, 100));
  } while (Date.now() < composerDeadline);
  const stop = () => visible('[data-testid="stop-button"], [data-testid="stop-generating-button"], button[aria-label="Stop streaming"], button[aria-label="Stop generating"]');
  if (!input) return { error: 'browser_submit_unavailable' };
  if (input.innerText.trim()) return { error: 'browser_draft_present' };
  if (stop()) return { error: 'browser_page_busy' };
  if (selection?.kind !== 'picker' || !['GPT-5.5', 'GPT-5.6 Sol'].includes(selection.modelLabel))
    return { error: 'browser_model_unavailable' };
  const waitFor = async read => {
    const deadline = Date.now() + 4000;
    do {
      const value = read();
      if (value) return value;
      await new Promise(resolve => setTimeout(resolve, 80));
    } while (Date.now() < deadline);
    return null;
  };
  const picker = () => visible('[aria-label="Select ChatGPT model"], [data-testid="model-switcher-dropdown-button"]');
  const items = () => [...document.querySelectorAll('[role="menuitem"], [role="menuitemradio"], [role="option"]')].filter(item => item.getClientRects().length);
  const button = picker();
  if (!button) return { error: 'browser_model_unavailable' };
  if (button.getAttribute('aria-expanded') !== 'true') button.click();
  const matchesModel = item => {
    const label = (item.innerText || item.textContent).replace(/\s+/g, ' ').trim();
    return label === selection.modelLabel || label.startsWith(selection.modelLabel + ' ');
  };
  const first = await waitFor(() => items().find(item => matchesModel(item) || item.textContent.trim() === 'Select model' || item.getAttribute('aria-label') === 'Select model'));
  if (!first) return { error: 'browser_model_unavailable' };
  if (!matchesModel(first)) first.click();
  const model = await waitFor(() => items().find(matchesModel));
  if (!model) return { error: 'browser_model_unavailable' };
  model.click();
  if (!await waitFor(() => model.getAttribute('aria-checked') === 'true' || !model.isConnected || !model.getClientRects().length))
    return { error: 'browser_model_unavailable' };
  return { modelSelected: true };
}

async function chatgptEffortSelection(selection) {
  const picker = [...document.querySelectorAll('[aria-label="Select ChatGPT model"], [data-testid="model-switcher-dropdown-button"]')].find(node => node.getClientRects().length);
  if (!picker) return { error: 'browser_effort_unavailable' };
  if (picker.getAttribute('aria-expanded') !== 'true') picker.click();
  const deadline = Date.now() + 4000;
  let power;
  do {
    power = [...document.querySelectorAll('[role="menuitem"], [role="menuitemradio"], [role="option"]')].find(item => item.getClientRects().length && (item.textContent.trim() === 'Power' || item.getAttribute('aria-label') === 'Power'));
    if (power) break;
    await new Promise(resolve => setTimeout(resolve, 80));
  } while (Date.now() < deadline);
  const status = [...document.querySelectorAll('[role="status"]')].map(item => item.textContent).join(' ');
  const count = status.match(/(\d+)\s+of\s+(\d+)/i);
  if (!power || !count || selection.effortIndex >= Number(count[2]))
    return { error: 'browser_effort_unavailable' };
  power.focus();
  return { steps: Number(count[2]) };
}

function chatgptSubmittedMessage(postData, prompt) {
  try {
    const request = JSON.parse(postData);
    const messages = request.messages || request.input_messages || (request.message ? [request.message] : []);
    if (!Array.isArray(messages)) return null;
    const message = messages.findLast(item => (item?.author?.role || item?.role) === 'user');
    const parts = message?.content?.parts || (typeof message?.content === 'string' ? [message.content] : message?.content);
    if (!Array.isArray(parts) || parts.length !== 1) return null;
    const text = typeof parts[0] === 'string' ? parts[0] : parts[0]?.text;
    const normalized = value => String(value || '').replace(/\s+/g, ' ').trim();
    if (typeof text !== 'string' || normalized(text) !== normalized(prompt)) return null;
    return { id: typeof message.id === 'string' ? message.id : '' };
  } catch { return null; }
}

function chatgptAssistantSnapshot() {
  const nodes = [...document.querySelectorAll('[data-message-author-role="assistant"], [data-content-search-unit-key$=":assistant"]')].filter(node => node.getClientRects().length);
  const key = node => node.getAttribute('data-message-id') || node.getAttribute('data-chatgpt-search-message-ids') ||
    node.querySelector('[data-chatgpt-selection-message-id]')?.getAttribute('data-chatgpt-selection-message-id') ||
    node.getAttribute('data-content-search-unit-key') || '';
  return { count: nodes.length, keys: nodes.map(key).filter(Boolean) };
}

function chatgptCompletedAssistant(prompt, previousAssistants, submittedMessage = null) {
  const nodes = [...document.querySelectorAll('[data-message-author-role="assistant"], [data-content-search-unit-key$=":assistant"]')].filter(node => node.getClientRects().length);
  const last = nodes.at(-1);
  if (!last) return null;
  const key = last.getAttribute('data-message-id') || last.getAttribute('data-chatgpt-search-message-ids') ||
    last.querySelector('[data-chatgpt-selection-message-id]')?.getAttribute('data-chatgpt-selection-message-id') ||
    last.getAttribute('data-content-search-unit-key') || '';
  // The website virtualizes older turns: the rendered count can stay constant
  // when a new answer replaces an unmounted old answer. Track stable identity.
  if (typeof previousAssistants === 'object' && previousAssistants !== null) {
    if (key ? previousAssistants.keys.includes(key) : nodes.length <= previousAssistants.count) return null;
  } else if (nodes.length <= previousAssistants) return null;
  const user = [...document.querySelectorAll('[data-message-author-role="user"], [data-user-message-bubble]')].filter(node => node.getClientRects().length).at(-1);
  const normalized = value => String(value || '').replace(/\s+/g, ' ').trim();
  if (!user) return null;
  if (!(user.compareDocumentPosition(last) & Node.DOCUMENT_POSITION_FOLLOWING)) return null;
  const currentMessageIds = user.closest('[data-chatgpt-search-message-ids]')?.getAttribute('data-chatgpt-search-message-ids')?.split(/\s+/);
  if (submittedMessage?.id && currentMessageIds && !currentMessageIds.includes(submittedMessage.id)) return null;
  // Large agent prompts are truncated by the website. Expand the new prompt
  // before checking ownership, and exclude its Show more/less controls.
  // innerText preserves paragraph boundaries created by contenteditable input;
  // textContent would join adjacent paragraphs and fail on multiline context.
  let userText = user.innerText.trim();
  for (const button of [...user.querySelectorAll('button')].reverse()) {
    const label = button.innerText.trim();
    if (label && userText.endsWith(label)) userText = userText.slice(0, -label.length).trim();
  }
  if (!submittedMessage && normalized(userText) !== normalized(prompt)) {
    const expand = [...user.querySelectorAll('button')].find(button => button.textContent.trim() === 'Show more');
    expand?.click();
    return null;
  }
  const article = last.closest('[data-talvt-turn-state], article') || last.parentElement;
  const stopped = [...document.querySelectorAll('[data-testid="stop-button"], [data-testid="stop-generating-button"], button[aria-label="Stop streaming"], button[aria-label="Stop generating"]')].some(node => node.getClientRects().length);
  const done = article?.querySelector('[data-testid="copy-turn-action-button"], button[aria-label="Copy"], button[aria-label="Copy response"]');
  const failed = article?.querySelector('[role="alert"], [data-testid="conversation-error"]');
  const state = article?.getAttribute('data-talvt-turn-state');
  if (stopped || !done || failed || (state && state !== 'complete')) return null;
  const text = (last.querySelector('[data-markdown-text-style="assistant-message"], .markdown, .prose') || last).innerText;
  if (!text.trim()) return null;
  return {
    text,
    conversationId: location.pathname.match(/^\/c\/([A-Za-z0-9-]+)$/)?.[1] || '',
    turnExchangeId: last.getAttribute('data-message-id') || last.querySelector('[data-chatgpt-selection-message-id]')?.getAttribute('data-chatgpt-selection-message-id') || last.getAttribute('data-chatgpt-search-message-ids')?.split(/\s+/)[0] || article?.getAttribute('data-turn-id') || '',
  };
}

async function chatgptNativeTurn(tab, work) {
  if (tab.provider !== 'chatgpt-web' || typeof work.prompt !== 'string' || !work.prompt.trim() ||
      work.prompt.length > 4 * 1024 * 1024 || !Number.isInteger(work.selection?.effortIndex) ||
      work.selection.effortIndex < 0 || work.selection.effortIndex > 4)
    throw chatgptTurnError('browser_submit_unavailable');
  const model = await evaluate(tab, `(${chatgptComposerSelection.toString()})(${JSON.stringify(work.selection)})`);
  if (!model?.modelSelected || model.error) throw chatgptTurnError(model?.error || 'browser_model_unavailable');
  const key = async name => {
    const virtualKey = { Enter: 13, Escape: 27, ArrowLeft: 37, ArrowRight: 39 }[name];
    const event = { key: name, code: name, windowsVirtualKeyCode: virtualKey, nativeVirtualKeyCode: virtualKey };
    await chrome.debugger.sendCommand({ tabId: tab.id }, 'Input.dispatchKeyEvent', { type: 'keyDown', ...event });
    await chrome.debugger.sendCommand({ tabId: tab.id }, 'Input.dispatchKeyEvent', { type: 'keyUp', ...event });
  };
  // Real key input dismisses both nested and outer website menus. A synthetic
  // picker click can reopen the submenu instead of closing it on new chats.
  await key('Escape');
  await key('Escape');
  await new Promise(resolve => setTimeout(resolve, 200));
  const selected = await evaluate(tab, `(${chatgptEffortSelection.toString()})(${JSON.stringify(work.selection)})`);
  if (!selected || selected.error) throw chatgptTurnError(selected?.error || 'browser_effort_unavailable');
  for (let index = 0; index < selected.steps; index++) await key('ArrowLeft');
  for (let index = 0; index < work.selection.effortIndex; index++) await key('ArrowRight');
  const effort = await evaluate(tab, String.raw`(() => { const status = [...document.querySelectorAll('[role="status"]')].map(item => item.textContent).join(' '); const count = status.match(/(\d+)\s+of\s+(\d+)/i); return count ? Number(count[1]) - 1 : null; })()`);
  await key('Escape');
  if (effort !== work.selection.effortIndex) throw chatgptTurnError('browser_effort_unavailable');
  // Closing the picker restores focus asynchronously; let that finish before
  // focusing the composer so input cannot reopen the model menu.
  await new Promise(resolve => setTimeout(resolve, 200));
  const ready = await evaluate(tab, `(() => { const input = [...document.querySelectorAll('#prompt-textarea, [contenteditable="true"][role="textbox"], [contenteditable="true"].ProseMirror')].find(node => node.getClientRects().length); if (!input || input.innerText.trim()) return null; input.focus(); return { assistants: (${chatgptAssistantSnapshot.toString()})() }; })()`);
  if (!ready) throw chatgptTurnError('browser_draft_present');
  await chrome.debugger.sendCommand({ tabId: tab.id }, 'Network.enable', { maxPostDataSize: 4 * 1024 * 1024 });
  let responseId = null;
  let accepted = false;
  let body = null;
  let submitted = false;
  let frameBytes = 0;
  const frames = [];
  const submittedMessages = new Map();
  let fail, finish;
  const completed = new Promise((resolve, reject) => { finish = resolve; fail = reject; });
  completed.catch(() => {});
  const onEvent = (source, method, params) => {
    if (source.tabId !== tab.id || !submitted) return;
    if (method === 'Network.requestWillBeSent' && params.request?.method === 'POST') {
      let url;
      try { url = new URL(params.request.url); } catch { return; }
      if (url.origin === 'https://chatgpt.com' && /^\/backend-api\/(?:f\/)?conversation$/.test(url.pathname)) {
        const message = chatgptSubmittedMessage(params.request.postData, work.prompt);
        if (message) submittedMessages.set(params.requestId, message);
      }
    }
    if (method === 'Network.responseReceived') {
      let url;
      try { url = new URL(params.response.url); } catch { return; }
      if (url.origin === 'https://chatgpt.com' && /^\/backend-api\/(?:f\/)?conversation$/.test(url.pathname)) {
        if (responseId && responseId !== params.requestId) return;
        responseId = params.requestId;
        if (params.response.status < 200 || params.response.status >= 300)
          fail(chatgptTurnError('browser_response_incomplete', 'http'));
        else accepted = true;
      }
    }
    if (method === 'Network.loadingFailed' && params.requestId === responseId && !params.canceled)
      fail(chatgptTurnError('browser_response_incomplete', 'network'));
    if (method === 'Network.loadingFinished' && params.requestId === responseId)
      void chrome.debugger.sendCommand({ tabId: tab.id }, 'Network.getResponseBody', { requestId: responseId }).then(result => {
        body = result.base64Encoded ? atob(result.body) : result.body;
        if (typeof body !== 'string' || body.length > 16 * 1024 * 1024)
          fail(chatgptTurnError('browser_response_incomplete', 'body'));
      }, () => { /* A conduit handoff may discard the HTTP body; require fresh completed UI evidence instead. */ });
    if (method === 'Network.webSocketFrameReceived' && params.response?.opcode === 1) {
      const frame = params.response.payloadData;
      if (typeof frame !== 'string') return;
      frameBytes += frame.length;
      if (frames.length >= 2048 || frameBytes > 16 * 1024 * 1024)
        fail(chatgptTurnError('browser_response_incomplete', 'frames'));
      else frames.push(frame);
    }
  };
  chrome.debugger.onEvent.addListener(onEvent);
  cancelChatGPT = () => fail(new Error('ChatGPT request cancelled'));
  const timer = setTimeout(() => fail(chatgptTurnError('browser_response_incomplete', 'timeout')), 180000);
  let polling = false;
  const interval = setInterval(async () => {
    if (polling || !accepted) return;
    polling = true;
    try {
      const fresh = await evaluate(tab, `(${chatgptCompletedAssistant.toString()})(${JSON.stringify(work.prompt)}, ${JSON.stringify(ready.assistants)}, ${JSON.stringify(submittedMessages.get(responseId) || null)})`);
      if (fresh?.text) finish({ body: body || '', frames, ...fresh });
    } catch { fail(chatgptTurnError('browser_response_incomplete', 'capture')); }
    finally { polling = false; }
  }, 500);
  try {
    await chrome.debugger.sendCommand({ tabId: tab.id }, 'Input.insertText', { text: work.prompt });
    await new Promise(resolve => setTimeout(resolve, 200));
    submitted = true;
    const sent = await evaluate(tab, `(() => { const button = [...document.querySelectorAll('[data-testid="send-button"], button[aria-label="Send"], button[aria-label="Send prompt"], button[aria-label="Send message"]')].find(node => node.getClientRects().length); if (!button || button.disabled || button.getAttribute('aria-disabled') === 'true') return false; button.click(); return true; })()`);
    if (!sent) throw chatgptTurnError('browser_submit_unavailable');
    return await completed;
  } finally {
    clearTimeout(timer);
    clearInterval(interval);
    chrome.debugger.onEvent.removeListener(onEvent);
    cancelChatGPT = null;
  }
}
