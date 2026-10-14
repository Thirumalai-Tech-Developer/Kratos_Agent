import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { isRecoveryEvent, isToolFormatFailure, isSavedToolFormatFailure, RECOVERY_NOTICE_MS } from '../frontend/src/chatRecovery.js';

const frontendRequire = createRequire(new URL('../frontend/package.json', import.meta.url));
const serviceRequire = createRequire(new URL('../services/omniroute/package.json', import.meta.url));
const { JSDOM } = serviceRequire('jsdom');
const { transformSync } = serviceRequire('esbuild');
const React = frontendRequire('react');
const { renderToStaticMarkup } = frontendRequire('react-dom/server');
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://127.0.0.1' });
globalThis.window = dom.window;
globalThis.document = dom.window.document;
globalThis.localStorage = dom.window.localStorage;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
dom.window.HTMLElement.prototype.scrollTo = () => {};
const { createRoot } = frontendRequire('react-dom/client');

let apiHandler;
const cache = new Map();
const unrelated = new Set(['Navbar', 'AgentHud', 'SessionsExplorer', 'TraceReplay', 'SqlPlayground', 'WorkspaceCommands', 'ChangesReview', 'ModelSettings', 'ModelPicker', 'JobsWorkspace']);
function loadSource(path) {
  if (cache.has(path)) return cache.get(path).exports;
  const module = { exports: {} };
  cache.set(path, module);
  const code = transformSync(readFileSync(path, 'utf8'), { loader: path.endsWith('.jsx') ? 'jsx' : 'js', format: 'cjs' }).code;
  const require = name => {
    if (name.endsWith('.css')) return undefined;
    if (!name.startsWith('.')) return frontendRequire(name);
    if (name === './api') return { apiFetch: (...args) => apiHandler(...args) };
    const component = name.split('/').pop();
    if (unrelated.has(component)) return { __esModule: true, default: () => null };
    if (component === 'Modals') return { AgentAuthModal: () => null, TechSpecsModal: () => null, PayloadModal: () => null };
    const absolute = resolve(dirname(path), name);
    return loadSource(existsSync(`${absolute}.jsx`) ? `${absolute}.jsx` : existsSync(`${absolute}.js`) ? `${absolute}.js` : absolute);
  };
  new Function('require', 'module', 'exports', code)(require, module, module.exports);
  return module.exports;
}
const sourceRoot = fileURLToPath(new URL('../frontend/src/', import.meta.url));
const App = loadSource(resolve(sourceRoot, 'App.jsx')).default;
const AgentArena = loadSource(resolve(sourceRoot, 'components/AgentArena.jsx')).default;
const oldFailure = 'Model request failed: The provider still returned invalid tool calls after 2 correction attempts. No tool calls from those rejected responses were executed.';
const flush = async () => { await React.act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); }); };

test('retry events are progress, while legacy detection is limited to the saved failed assistant response', () => {
  assert.equal(RECOVERY_NOTICE_MS, 5000);
  assert.equal(isRecoveryEvent({ type: 'retry', error: 'tool_call_format', recoverable: true }), true);
  assert.equal(isRecoveryEvent({ kind: 'runtime.retry' }), true);
  assert.equal(isRecoveryEvent({ type: 'done', status: 'failed' }), false);
  assert.equal(isRecoveryEvent({ type: 'retry', recoverable: false, reason: 'login_required' }), false);
  assert.equal(isSavedToolFormatFailure({ role: 'agent', status: 'failed', content: oldFailure }), true);
  assert.equal(isSavedToolFormatFailure({ role: 'user', status: 'failed', content: oldFailure }), false);
  assert.equal(isSavedToolFormatFailure({ role: 'agent', status: 'failed', content: `Analysis saved.\n${oldFailure}` }), false);
  assert.equal(isSavedToolFormatFailure({ role: 'agent', status: 'failed', content: 'Sign in again to continue.' }), false);
  for (const blocker of ['Sign in again to continue.', 'Permission denied: approve this action.', 'Cancelled by user.']) {
    assert.equal(isToolFormatFailure(`${oldFailure}\n${blocker}`), false);
  }
});

test('saved tool format failure renders one small truthful Activity link, without the old answer and two failure banners', () => {
  const html = renderToStaticMarkup(React.createElement(AgentArena, {
    messages: [{ role: 'agent', content: oldFailure, status: 'failed', tools: [{ id: 'saved', name: 'read_file', status: 'completed', output: 'saved file result' }] }],
    inputPrompt: '', isExecuting: false, executionError: oldFailure, onOpenActivity: () => {},
  }));
  assert.match(html, /Earlier attempt ended before completion/);
  assert.match(html, /View Activity/);
  assert.match(html, /read_file/);
  assert.doesNotMatch(html, /invalid tool calls|Needs attention|Retry task|execution-error/);
  const auth = renderToStaticMarkup(React.createElement(AgentArena, {
    messages: [{ role: 'agent', content: 'Sign in to continue.', status: 'failed' }], inputPrompt: '', executionError: 'Sign in to continue.',
  }));
  assert.match(auth, /Sign in to continue/);
  assert.match(auth, /Needs attention/);
  assert.match(auth, /Retry task/);
});

test('live recovery auto-dismisses after five seconds, remains processing through repeated retries, and only finishes on done', async () => {
  const realSetTimeout = globalThis.setTimeout;
  const realClearTimeout = globalThis.clearTimeout;
  const timers = new Map();
  let id = 0;
  globalThis.setTimeout = (callback, delay, ...args) => {
    if (delay !== RECOVERY_NOTICE_MS) return realSetTimeout(callback, delay, ...args);
    const handle = { recoveryTimer: ++id };
    timers.set(handle, () => callback(...args));
    return handle;
  };
  globalThis.clearTimeout = handle => timers.has(handle) ? timers.delete(handle) : realClearTimeout(handle);
  let controller;
  const stream = new ReadableStream({ start(value) { controller = value; } });
  const requests = [];
  apiHandler = async (path, options) => {
    requests.push({ path, options });
    if (path === '/api/sessions' && options?.method === 'POST') return new Response(JSON.stringify({ session_id: 'test-session' }), { status: 201, headers: { 'content-type': 'application/json' } });
    if (path === '/api/chat') return new Response(stream, { headers: { 'content-type': 'text/event-stream' } });
    const data = path === '/api/health' ? { busy: false } : ['/api/tools', '/api/sessions', '/api/events'].includes(path) ? [] : {};
    return new Response(JSON.stringify(data), { headers: { 'content-type': 'application/json' } });
  };
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  const send = async event => {
    await React.act(async () => { controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`)); });
    await flush();
  };
  try {
    await React.act(async () => { root.render(React.createElement(App)); });
    await flush();
    await React.act(async () => { [...host.querySelectorAll('button')].find(button => button.textContent.includes('Explore a project')).click(); });
    await React.act(async () => { [...host.querySelectorAll('button')].find(button => button.textContent.trim() === 'Send').click(); });
    assert.equal(requests.filter(request => request.path === '/api/chat').length, 1);
    await send({ type: 'retry', error: 'tool_call_format', recoverable: true, attempt: 3, strategy: 'single_json', message: oldFailure });
    assert.match(host.textContent, /Recovering… trying another method/);
    assert.match(host.textContent, /PROCESSING/);
    assert.equal(host.querySelector('[aria-label="Stop task"]').disabled, false);
    assert.equal(host.querySelector('.execution-error'), null);
    assert.doesNotMatch(host.textContent, /invalid tool calls|Needs attention|Retry task/);
    assert.equal(timers.size, 1);
    await send({ type: 'retry', error: 'tool_call_format', recoverable: true, attempt: 4, strategy: 'replan' });
    assert.equal(timers.size, 1, 'retry events do not restart the notice countdown');
    await React.act(async () => { const callbacks = [...timers.values()]; timers.clear(); callbacks.forEach(callback => callback()); });
    assert.equal(host.querySelector('.recovery-notice'), null);
    assert.match(host.textContent, /PROCESSING/);
    assert.equal(host.querySelector('[aria-label="Stop task"]').disabled, false);
    await send({ type: 'retry', error: 'tool_call_format', recoverable: true, attempt: 5, strategy: 'json' });
    assert.equal(host.querySelector('.recovery-notice'), null, 'continuous recovery does not pin or repeatedly reopen the notice');
    await send({ type: 'token', token: 'The project architecture is ready.' });
    assert.match(host.textContent, /The project architecture is ready/);
    assert.match(host.textContent, /PROCESSING/);
    await send({ type: 'retry', recoverable: true, attempt: 6, strategy: 'verify_and_replan' });
    assert.match(host.textContent, /Recovering… trying another method/);
    await send({ type: 'done', status: 'completed' });
    assert.equal(host.querySelector('.recovery-notice'), null, 'a terminal acknowledgement clears an active recovery notice');
    await React.act(async () => { controller.close(); });
    await flush();
    assert.equal(host.querySelector('[aria-label="Stop task"]'), null);
    assert.doesNotMatch(host.textContent, /PROCESSING|Needs attention|invalid tool calls/);
    assert.match(host.textContent, /The project architecture is ready/);
  } finally {
    await React.act(async () => { root.unmount(); });
    host.remove();
    globalThis.setTimeout = realSetTimeout;
    globalThis.clearTimeout = realClearTimeout;
  }
});

for (const terminal of [
  { status: 'failed', content: 'Model request failed: Sign in again to continue.', error: true, expected: /Needs attention/ },
  { status: 'paused', content: 'Permission required: approve access to this file.', expected: /This task is paused/ },
  { status: 'cancelled', content: 'Agent execution was interrupted.', expected: /Stopped by you/ },
]) {
  test(`recovery does not hide a ${terminal.status} terminal blocker or keep a misleading recovery notice`, async () => {
    let controller;
    const stream = new ReadableStream({ start(value) { controller = value; } });
    apiHandler = async (path, options) => {
      if (path === '/api/sessions' && options?.method === 'POST') return new Response(JSON.stringify({ session_id: 'test-session' }), { status: 201, headers: { 'content-type': 'application/json' } });
      if (path === '/api/chat') return new Response(stream, { headers: { 'content-type': 'text/event-stream' } });
      const data = path === '/api/health' ? { busy: false } : ['/api/tools', '/api/sessions', '/api/events'].includes(path) ? [] : {};
      return new Response(JSON.stringify(data), { headers: { 'content-type': 'application/json' } });
    };
    const host = document.createElement('div');
    document.body.append(host);
    const root = createRoot(host);
    const send = async event => {
      await React.act(async () => { controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`)); });
      await flush();
    };
    try {
      await React.act(async () => { root.render(React.createElement(App)); });
      await flush();
      await React.act(async () => { [...host.querySelectorAll('button')].find(button => button.textContent.includes('Explore a project')).click(); });
      await React.act(async () => { [...host.querySelectorAll('button')].find(button => button.textContent.trim() === 'Send').click(); });
      await send({ type: 'retry', reason: 'tool_call_format', recoverable: true, strategy: 'json' });
      assert.match(host.textContent, /Recovering… trying another method/);
      if (terminal.error) {
        await send({ type: 'error', message: terminal.content });
        assert.match(host.querySelector('.execution-error').textContent, /Sign in again to continue/);
        assert.equal(host.querySelector('.recovery-notice'), null);
      }
      await send({ type: 'done', status: terminal.status, result: terminal.content });
      assert.equal(host.querySelector('.recovery-notice'), null);
      await React.act(async () => { controller.close(); });
      await flush();
      assert.match(host.textContent, terminal.expected);
      assert.ok(host.textContent.includes(terminal.content));
      assert.equal(host.querySelector('[aria-label="Stop task"]'), null);
      assert.doesNotMatch(host.textContent, /PROCESSING|Recovering…/);
    } finally {
      await React.act(async () => { root.unmount(); });
      host.remove();
    }
  });
}
