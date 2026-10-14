import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import test from 'node:test';
import vm from 'node:vm';

const root = new URL('../src/kratos_agent/brain/chatgpt_browser_extension/', import.meta.url);
const source = await readFile(new URL('chatgpt-turn.js', root), 'utf8');
const background = await readFile(new URL('background.js', root), 'utf8');

function renderedJSDOM(BaseJSDOM) {
  return class extends BaseJSDOM {
    constructor(...args) {
      super(...args);
      this.window.HTMLElement.prototype.getClientRects = function () {
        return this.closest('[hidden]') ? [] : [{}];
      };
    }
  };
}

async function fixture(selectionError = null, missingBody = false) {
  const events = new Set();
  const commands = [];
  let renderTick;
  let hasFresh = false;
  const chrome = {
    tabs: { get: async () => ({ id: 7, url: 'https://chatgpt.com/' }) },
    debugger: {
      attach: async () => {}, detach: async () => {}, onDetach: { addListener() {} },
      onEvent: { addListener(fn) { events.add(fn); }, removeListener(fn) { events.delete(fn); } },
      sendCommand: async (target, method, params) => {
        commands.push({ method, params });
        if (method === 'Network.getResponseBody') {
          if (missingBody) throw new Error('Conduit handoff discarded the HTTP body');
          return { body: 'own network SSE' };
        }
        if (method === 'Runtime.evaluate') {
          const expression = params.expression;
          new vm.Script(expression); // Verify the actual serialized page program.
          const value = expression.includes('chatgptComposerSelection')
            ? selectionError ? { error: selectionError } : { modelSelected: true }
            : expression.includes('chatgptEffortSelection') ? { steps: 3 }
            : expression.includes('const count = status.match') ? 1
            : expression.includes('return { assistants:') ? { assistants: {count:2, keys:['old-assistant']} }
            : expression.includes('const nodes =') ? hasFresh ? { text: 'own completed answer' } : null : true;
          return { result: { value } };
        }
        return {};
      },
    },
    runtime: { onMessage: { addListener() {} } },
  };
  const context = { chrome, URL, AbortSignal,
    setTimeout(fn, delay) { if (delay === 200) { fn(); return 0; } return setTimeout(fn, delay); },
    clearTimeout, clearInterval() {}, atob, importScripts() {},
    setInterval(fn) { renderTick = fn; return 1; },
    KRATOS_BROWSER: { providers: { 'chatgpt-web': { url: 'https://chatgpt.com/' } } } };
  vm.runInNewContext(background + '\n' + source, context);
  await context.attach(7);
  return { context, events, commands, tick: () => renderTick(), fresh: () => { hasFresh = true; } };
}

const request = { prompt: 'own prompt', selection: { kind: 'picker', modelLabel: 'GPT-5.5', effortIndex: 1 } };
const tab = { id: 7, provider: 'chatgpt-web' };

test('ChatGPT returns only the new completed network response and removes listeners', async () => {
  const f = await fixture();
  const turn = f.context.chatgptNativeTurn(tab, request);
  await new Promise(resolve => setImmediate(resolve));
  for (const listener of f.events) {
    listener({ tabId: 8 }, 'Network.responseReceived', { requestId: 'other-tab', response: { url: 'https://chatgpt.com/backend-api/f/conversation', status: 200 } });
    listener({ tabId: 7 }, 'Network.webSocketFrameReceived', { response: { opcode: 1, payloadData: 'own frame' } });
    listener({ tabId: 7 }, 'Network.responseReceived', { requestId: 'own-response', response: { url: 'https://chatgpt.com/backend-api/f/conversation', status: 200 } });
    listener({ tabId: 7 }, 'Network.loadingFinished', { requestId: 'own-response' });
  }
  await new Promise(resolve => setImmediate(resolve));
  await f.tick();
  assert.equal(f.commands.find(c => c.method === 'Network.getResponseBody').params.requestId, 'own-response');
  assert.equal(f.events.size, 1, 'Old rendered messages must not finish a turn');
  f.fresh();
  await f.tick();
  const result = await turn;
  assert.equal(result.body, 'own network SSE');
  assert.deepEqual([...result.frames], ['own frame']);
  assert.equal(result.text, 'own completed answer');
  assert.equal(f.events.size, 0);
  assert.equal(f.commands.find(c => c.method === 'Input.insertText').params.text, 'own prompt');
  assert.ok(f.commands.some(c => c.method === 'Runtime.evaluate' && c.params.expression.includes('[data-testid="send-button"]')));
  await f.context.release();
});

test('ChatGPT Stop cancels the owning generation and cleans up the network listener', async () => {
  const f = await fixture();
  const turn = f.context.chatgptNativeTurn(tab, request);
  const rejected = assert.rejects(turn, /cancelled/);
  await new Promise(resolve => setImmediate(resolve));
  await f.context.release();
  await rejected;
  assert.equal(f.events.size, 0);
  assert.ok(f.commands.some(c => c.params?.expression?.includes('stop-generating-button')));
});

test('a successful conduit handoff still requires a fresh completed website reply', async () => {
  const f = await fixture(null, true);
  const turn = f.context.chatgptNativeTurn(tab, request);
  await new Promise(resolve => setImmediate(resolve));
  for (const listener of f.events) {
    listener({ tabId: 7 }, 'Network.responseReceived', { requestId: 'own-response', response: { url: 'https://chatgpt.com/backend-api/f/conversation', status: 200 } });
    listener({ tabId: 7 }, 'Network.loadingFailed', { requestId: 'own-response', canceled: true });
    listener({ tabId: 7 }, 'Network.loadingFinished', { requestId: 'own-response' });
  }
  await new Promise(resolve => setImmediate(resolve));
  await f.tick();
  assert.equal(f.events.size, 1, 'An accepted network request alone is not a reply');
  f.fresh();
  await f.tick();
  assert.equal((await turn).text, 'own completed answer');
  assert.equal(f.events.size, 0);
  await f.context.release();
});

test('completed UI capture rejects old, unrelated, active and errored messages', () => {
  const require = createRequire(new URL('../services/omniroute/package.json', import.meta.url));
  const JSDOM = renderedJSDOM(require('jsdom').JSDOM);
  const dom = new JSDOM('<article><div data-message-author-role="user">own prompt</div><div data-message-author-role="assistant" data-message-id="new-message"><div class="markdown">new answer</div></div><button aria-label="Copy"></button></article>', { runScripts: 'outside-only', url: 'https://chatgpt.com/c/current-conversation' });
  const { window } = dom;
  Object.defineProperty(window.HTMLElement.prototype, 'innerText', { get() { return this.textContent; } });
  window.eval(source);
  try {
    assert.equal(window.chatgptCompletedAssistant('own prompt', 1), null, 'Previously rendered answer');
    assert.equal(window.chatgptCompletedAssistant('other prompt', 0), null, 'Different user request');
    const result = window.chatgptCompletedAssistant('own prompt', 0);
    assert.equal(result.text, 'new answer');
    assert.equal(result.conversationId, 'current-conversation');
    assert.equal(result.turnExchangeId, 'new-message');
    const stop = window.document.createElement('button');
    stop.setAttribute('data-testid', 'stop-button');
    window.document.body.append(stop);
    assert.equal(window.chatgptCompletedAssistant('own prompt', 0), null, 'Still generating');
    stop.remove();
    const error = window.document.createElement('div');
    error.setAttribute('role', 'alert');
    window.document.querySelector('article').append(error);
    assert.equal(window.chatgptCompletedAssistant('own prompt', 0), null, 'Partial failed reply');
  } finally { window.close(); }
});

test('a draft, active website generation or unavailable model sends no prompt', async () => {
  for (const error of ['browser_draft_present', 'browser_page_busy', 'browser_model_unavailable', 'browser_effort_unavailable']) {
    const f = await fixture(error);
    await assert.rejects(f.context.chatgptNativeTurn(tab, request), failure => failure.code === error);
    assert.ok(!f.commands.some(c => c.method === 'Input.insertText'));
    assert.equal(f.events.size, 0);
    await f.context.release();
  }
});

test('the current website turn layout returns only the newly completed answer', () => {
  const require = createRequire(new URL('../services/omniroute/package.json', import.meta.url));
  const JSDOM = renderedJSDOM(require('jsdom').JSDOM);
  const dom = new JSDOM('<div data-talvt-turn-state="complete"><div data-user-message-bubble="true">own prompt</div><div data-content-search-unit-key="fallback-turn-0:2:assistant"><h4>ChatGPT said:</h4><div data-chatgpt-selection-message-id="actual-message"><div data-markdown-text-style="assistant-message">new answer</div></div></div><button aria-label="Copy"></button></div>', { runScripts: 'outside-only', url: 'https://chatgpt.com/c/current-conversation' });
  const { window } = dom;
  Object.defineProperty(window.HTMLElement.prototype, 'innerText', { get() { return this.textContent; } });
  window.eval(source);
  try {
    assert.equal(window.chatgptCompletedAssistant('own prompt', 1), null);
    assert.equal(window.chatgptCompletedAssistant('different prompt', 0), null);
    const result = window.chatgptCompletedAssistant('own prompt', 0);
    assert.equal(result.text, 'new answer', 'Accessibility headings are excluded');
    assert.equal(result.turnExchangeId, 'actual-message');
    const turn = window.document.querySelector('[data-talvt-turn-state]');
    turn.setAttribute('data-talvt-turn-state', 'streaming');
    assert.equal(window.chatgptCompletedAssistant('own prompt', 0), null);
    turn.setAttribute('data-talvt-turn-state', 'error');
    assert.equal(window.chatgptCompletedAssistant('own prompt', 0), null);
    turn.setAttribute('data-talvt-turn-state', 'complete');
    turn.querySelector('button').remove();
    assert.equal(window.chatgptCompletedAssistant('own prompt', 0), null);
  } finally { window.close(); }
});

test('a rejected website response cannot be replaced with old rendered text', async () => {
  const f = await fixture();
  const turn = f.context.chatgptNativeTurn(tab, request);
  const rejected = assert.rejects(turn, failure => failure.code === 'browser_response_incomplete');
  await new Promise(resolve => setImmediate(resolve));
  f.fresh();
  for (const listener of f.events) listener({ tabId: 7 }, 'Network.responseReceived', {
    requestId: 'own-response', response: { url: 'https://chatgpt.com/backend-api/conversation', status: 429 },
  });
  await rejected;
  assert.equal(f.events.size, 0);
  await f.context.release();
});

test('a collapsed agent prompt must expand and match fully before its answer is returned', () => {
  const require = createRequire(new URL('../services/omniroute/package.json', import.meta.url));
  const JSDOM = renderedJSDOM(require('jsdom').JSDOM);
  const dom = new JSDOM('<div data-talvt-turn-state="complete"><div data-user-message-bubble="true"><span class="prompt">System: partial preview</span><span aria-hidden="true">…</span><button>Show more</button></div><div data-content-search-unit-key="turn:assistant"><div data-markdown-text-style="assistant-message">Hello!</div></div><button aria-label="Copy"></button></div>', { runScripts: 'outside-only' });
  const { window } = dom;
  Object.defineProperty(window.HTMLElement.prototype, 'innerText', { get() { return this.textContent; } });
  const prompt = 'System: full instructions\n\nUser: hii';
  const expand = window.document.querySelector('[data-user-message-bubble] button');
  expand.onclick = () => {
    window.document.querySelector('.prompt').textContent = prompt;
    window.document.querySelector('[aria-hidden="true"]').remove();
    expand.textContent = 'Show less';
  };
  window.eval(source);
  try {
    assert.equal(window.chatgptCompletedAssistant(prompt, 0), null, 'A preview cannot establish prompt ownership');
    assert.equal(expand.textContent, 'Show less');
    assert.equal(window.chatgptCompletedAssistant(prompt, 0).text, 'Hello!');
    assert.equal(window.chatgptCompletedAssistant('System: full instructions\n\nUser: other request', 0), null);
  } finally { window.close(); }
});

test('rendered multiline context preserves paragraph boundaries when checking the prompt', () => {
  const require = createRequire(new URL('../services/omniroute/package.json', import.meta.url));
  const JSDOM = renderedJSDOM(require('jsdom').JSDOM);
  const dom = new JSDOM('<div data-talvt-turn-state="complete"><div data-user-message-bubble="true"><p>System: instructions</p><p>User: hii</p><button>Show less</button></div><div data-content-search-unit-key="turn:assistant"><div data-markdown-text-style="assistant-message">Hello!</div></div><button aria-label="Copy"></button></div>', { runScripts: 'outside-only' });
  const { window } = dom;
  Object.defineProperty(window.HTMLElement.prototype, 'innerText', { get() {
    return this.hasAttribute('data-user-message-bubble')
      ? [...this.children].map(node=>node.textContent).join('\n') : this.textContent;
  } });
  window.eval(source);
  try {
    assert.equal(window.chatgptCompletedAssistant('System: instructions\n\nUser: hii', 0).text, 'Hello!');
    assert.equal(window.chatgptCompletedAssistant('System: instructions\n\nUser: different', 0), null);
  } finally { window.close(); }
});

test('an exact submitted request identifies its completed turn even when the prompt is collapsed', () => {
  const require = createRequire(new URL('../services/omniroute/package.json', import.meta.url));
  const JSDOM = renderedJSDOM(require('jsdom').JSDOM);
  const dom = new JSDOM('<div data-talvt-turn-state="complete"><div data-chatgpt-search-message-ids="own-user"><div data-user-message-bubble="true">partial preview<button>Show more</button></div></div><div data-content-search-unit-key="turn:assistant"><div data-markdown-text-style="assistant-message">Hello!</div></div><button aria-label="Copy"></button></div>', { runScripts: 'outside-only' });
  const { window } = dom;
  Object.defineProperty(window.HTMLElement.prototype, 'innerText', { get() { return this.textContent; } });
  window.eval(source);
  const prompt = 'System: full context\n\nUser: hii';
  const body = message => JSON.stringify({messages:[message]});
  try {
    const message = {id:'own-user', author:{role:'user'},content:{parts:[prompt]}};
    const submitted = window.chatgptSubmittedMessage(body(message), prompt);
    assert.equal(submitted.id, 'own-user');
    assert.equal(window.chatgptSubmittedMessage(JSON.stringify({input_messages:[{id:'own-user',role:'user',content:[{type:'text',text:prompt.replaceAll('\n','\r\n')}]}]}), prompt).id, 'own-user');
    assert.equal(window.chatgptSubmittedMessage(body(message), 'different'), null);
    assert.equal(window.chatgptSubmittedMessage(body({...message, author:{role:'assistant'}}), prompt), null);
    assert.equal(window.chatgptSubmittedMessage('{invalid', prompt), null);
    assert.equal(window.chatgptCompletedAssistant(prompt, 0, submitted).text, 'Hello!');
    assert.equal(window.chatgptCompletedAssistant(prompt, 1, submitted), null, 'An old answer is still rejected');
    assert.equal(window.chatgptCompletedAssistant(prompt, 0, {id:'different-user'}), null);
    const turn = window.document.querySelector('[data-talvt-turn-state]');
    turn.setAttribute('data-talvt-turn-state', 'error');
    assert.equal(window.chatgptCompletedAssistant(prompt, 0, submitted), null);
  } finally { window.close(); }
});

test('the current nested model picker selects the exact model before adjusting effort', async () => {
  const require = createRequire(new URL('../services/omniroute/package.json', import.meta.url));
  const JSDOM = renderedJSDOM(require('jsdom').JSDOM);
  const dom = new JSDOM('<div hidden><div id="prompt-textarea" contenteditable="true">preserved hidden draft</div><button aria-label="Select ChatGPT model" aria-expanded="true">Old hidden picker</button><button data-testid="stop-button"></button></div><div contenteditable="true" role="textbox"></div><button id="visible-picker" aria-label="Select ChatGPT model">High</button><div id="menu"></div>', { runScripts: 'outside-only' });
  const { window } = dom;
  Object.defineProperty(window.HTMLElement.prototype, 'innerText', { get() { return this.textContent; } });
  const menu = window.document.getElementById('menu');
  let selected = '';
  const picker = window.document.getElementById('visible-picker');
  picker.onclick = () => {
    if (selected) {
      window.setTimeout(() => { menu.innerHTML = '<div role="menuitem" aria-label="Power" tabindex="0"></div><div role="status">High, 3 of 3.</div>'; }, 300);
      return;
    }
    window.setTimeout(() => {
      menu.innerHTML = '<div role="menuitem" aria-label="Select model">High</div>';
      menu.firstChild.onclick = () => {
        window.setTimeout(() => {
          menu.innerHTML = '<div role="menuitemradio">GPT-6</div><div role="menuitemradio">GPT-5.5 <span>Leaving on October 14</span></div>';
          menu.lastChild.onclick = () => {
            selected = 'GPT-5.5';
            window.setTimeout(() => menu.replaceChildren(), 300);
          };
        }, 300);
      };
    }, 300);
  };
  window.eval(source);
  try {
    const result = await window.chatgptComposerSelection(request.selection);
    assert.equal(result.modelSelected, true);
    assert.equal(selected, 'GPT-5.5');
    const effort = await window.chatgptEffortSelection(request.selection);
    assert.equal(effort.steps, 3);
    assert.equal(window.document.activeElement.getAttribute('aria-label'), 'Power');
    assert.equal(window.document.querySelector('[hidden] #prompt-textarea').textContent, 'preserved hidden draft');
  } finally { window.close(); }
});

test('virtualized turns require a new assistant identity after the submitted user message', () => {
  const require = createRequire(new URL('../services/omniroute/package.json', import.meta.url));
  const JSDOM = renderedJSDOM(require('jsdom').JSDOM);
  const dom = new JSDOM('<div data-talvt-turn-state="complete"><div data-user-message-bubble="true">old prompt</div><div data-content-search-unit-key="old:assistant" data-chatgpt-search-message-ids="old-assistant"><div data-markdown-text-style="assistant-message">Old answer</div></div><button aria-label="Copy"></button></div>', { runScripts: 'outside-only', url: 'https://chatgpt.com/c/current-conversation' });
  const { window } = dom;
  Object.defineProperty(window.HTMLElement.prototype, 'innerText', { get() { return this.textContent; } });
  window.eval(source);
  try {
    const before = window.chatgptAssistantSnapshot();
    assert.equal(before.count, 1);
    assert.equal(window.chatgptCompletedAssistant('old prompt', before), null);
    window.document.body.innerHTML = '<div data-talvt-turn-state="complete"><div data-chatgpt-search-message-ids="own-user"><div data-user-message-bubble="true">own prompt</div></div><div data-content-search-unit-key="new:assistant" data-chatgpt-search-message-ids="new-assistant"><div data-markdown-text-style="assistant-message">Hello!</div></div><button aria-label="Copy"></button></div>';
    const reply = window.chatgptCompletedAssistant('own prompt', before, {id:'own-user'});
    assert.equal(reply.text, 'Hello!');
    assert.equal(reply.turnExchangeId, 'new-assistant');
    assert.equal(window.chatgptCompletedAssistant('own prompt', before, {id:'other-user'}), null);
    const lastUser = window.document.createElement('div');
    lastUser.setAttribute('data-user-message-bubble', 'true');
    lastUser.textContent = 'own prompt';
    window.document.body.append(lastUser);
    assert.equal(window.chatgptCompletedAssistant('own prompt', before), null, 'An answer before the current request is not its reply');
  } finally { window.close(); }
});
