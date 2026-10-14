import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { withSelectedCatalogModel } from '../frontend/src/modelCatalog.js';

const frontendRequire = createRequire(new URL('../frontend/package.json', import.meta.url));
const serviceRequire = createRequire(new URL('../services/omniroute/package.json', import.meta.url));
const { JSDOM } = serviceRequire('jsdom');
const { transformSync } = serviceRequire('esbuild');
const React = frontendRequire('react');
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://127.0.0.1' });
globalThis.window = dom.window;
globalThis.document = dom.window.document;
globalThis.localStorage = dom.window.localStorage;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
dom.window.HTMLElement.prototype.scrollTo = () => {};
dom.window.HTMLElement.prototype.scrollIntoView = () => {};
dom.window.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
dom.window.HTMLDialogElement.prototype.close = function () { this.open = false; };
const { createRoot } = frontendRequire('react-dom/client');
let apiHandler;
const cache = new Map();
const unrelated = new Set(['AgentHud', 'SessionsExplorer', 'TraceReplay', 'SqlPlayground', 'WorkspaceCommands', 'ChangesReview', 'ModelSettings', 'JobsWorkspace']);
function loadSource(path) {
  if (cache.has(path)) return cache.get(path).exports;
  const module = { exports: {} };
  cache.set(path, module);
  const code = transformSync(readFileSync(path, 'utf8'), { loader: path.endsWith('.jsx') ? 'jsx' : 'js', format: 'cjs' }).code;
  const require = name => {
    if (name.endsWith('.css')) return undefined;
    if (!name.startsWith('.')) return frontendRequire(name);
    if (name === './api' || name === '../api') return { apiFetch: (...args) => apiHandler(...args) };
    const component = name.split('/').pop();
    if (component === 'Navbar') return { __esModule: true, default: props => React.createElement('button', { onClick: props.onRefresh }, 'Refresh workspace') };
    if (unrelated.has(component)) return { __esModule: true, default: () => null };
    if (component === 'Modals') return { AgentAuthModal: () => null, TechSpecsModal: () => null, PayloadModal: () => null };
    const absolute = resolve(dirname(path), name);
    return loadSource(existsSync(`${absolute}.jsx`) ? `${absolute}.jsx` : existsSync(`${absolute}.js`) ? `${absolute}.js` : absolute);
  };
  new Function('require', 'module', 'exports', code)(require, module, module.exports);
  return module.exports;
}
const App = loadSource(resolve(fileURLToPath(new URL('../frontend/src/', import.meta.url)), 'App.jsx')).default;
const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'content-type': 'application/json' } });
const flush = async () => { await React.act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); }); };
async function mountedApp(handler) {
  apiHandler = handler;
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  await React.act(async () => { root.render(React.createElement(App)); });
  await flush();
  return {
    host,
    click: async selector => { await React.act(async () => { const button = typeof selector === 'function' ? [...host.querySelectorAll('button')].find(selector) : host.querySelector(selector); assert.ok(button, 'required button exists'); button.click(); }); await flush(); },
    close: async () => { await React.act(async () => { root.unmount(); }); host.remove(); },
  };
}
function defaultResponse(path, model = 'shared-model') {
  if (path === '/api/health') return json({ busy: false });
  if (path === '/api/telemetry') return json({ model });
  return json(['/api/tools', '/api/sessions', '/api/events'].includes(path) ? [] : {});
}

test('selection updates one cached connection while preserving capability metadata and duplicate model IDs', () => {
  const catalog = [{ id: 'same', selection_key: 'account:a', is_configured: true, supports_image_input: false }, { id: 'same', selection_key: 'account:b', is_configured: false }, { id: 'other', selection_key: 'gateway:other', is_configured: false }];
  const selected = withSelectedCatalogModel(catalog, 'same', 'account:b');
  assert.deepEqual(selected.map(model => model.is_configured), [false, true, false]);
  assert.equal(selected[0].supports_image_input, false);
  assert.equal(catalog[0].is_configured, true, 'old snapshot is not mutated');
});

test('catalog is read once across picker opens, selection, telemetry/workspace refresh; only Refetch updates it', async () => {
  const requests = [];
  let selectedConnection = 'account:a';
  let finishRefetch;
  let refetchPending = false;
  let failRefetch = false;
  const original = [{ id: 'shared-model', selection_key: 'account:a', name: 'Account One', provider: 'ChatGPT', is_configured: true }, { id: 'shared-model', selection_key: 'account:b', name: 'Account Two', provider: 'ChatGPT', is_configured: false }];
  const app = await mountedApp(async (path, options = {}) => {
    requests.push({ path, options });
    if (path === '/api/models' && options.method === 'POST') {
      selectedConnection = JSON.parse(options.body).connection;
      return json({ model: 'shared-model', selection_key: selectedConnection });
    }
    if (path === '/api/models') return json({ models: original, model: 'shared-model' });
    if (path === '/api/models?refresh=1') {
      if (refetchPending) await new Promise(resolve => { finishRefetch = resolve; });
      if (failRefetch) return json({ error: 'OmniRoute is unavailable.' }, 503);
      return json({ models: [...withSelectedCatalogModel(original, 'shared-model', selectedConnection), { id: 'new', name: 'New upstream model', provider: 'OmniRoute' }], model: 'shared-model', notices: ['Saved refreshed catalog.'] });
    }
    return defaultResponse(path);
  });
  const modelGets = () => requests.filter(request => request.path.startsWith('/api/models') && request.options.method !== 'POST');
  try {
    assert.equal(modelGets().length, 1);
    await app.click('[aria-label^="Change model"]');
    assert.match(app.host.textContent, /Account One/);
    assert.doesNotMatch(app.host.textContent, /Loading models/);
    await app.click('[aria-label="Close model picker"]');
    await app.click('[aria-label^="Change model"]');
    await app.click(button => button.getAttribute('role') === 'option' && button.textContent.includes('Account Two'));
    assert.equal(app.host.querySelector('dialog'), null);
    assert.equal(modelGets().length, 1, 'model selection must not fetch the catalog');
    await app.click(button => button.textContent === 'Refresh workspace');
    await app.click('[aria-label^="Change model"]');
    const options = [...app.host.querySelectorAll('[role="option"]')];
    assert.equal(options.find(option => option.textContent.includes('Account Two')).getAttribute('aria-selected'), 'true');
    assert.equal(options.find(option => option.textContent.includes('Account One')).getAttribute('aria-selected'), 'false');
    assert.equal(modelGets().length, 1, 'reopen and telemetry refresh reuse the same catalog');
    refetchPending = true;
    await app.click('[aria-label="Refetch available models"]');
    assert.equal(modelGets().length, 2);
    assert.equal(modelGets()[1].path, '/api/models?refresh=1');
    assert.match(app.host.textContent, /Account One/);
    assert.match(app.host.textContent, /Refetching catalog/);
    assert.equal(app.host.querySelector('[aria-label="Refetch available models"]').disabled, true);
    await React.act(async () => { finishRefetch(); });
    await flush();
    assert.match(app.host.textContent, /New upstream model/);
    assert.match(app.host.textContent, /Saved refreshed catalog/);
    await app.click('[aria-label="Close model picker"]');
    await app.click('[aria-label^="Change model"]');
    assert.match(app.host.textContent, /New upstream model/);
    assert.equal(modelGets().length, 2);
    failRefetch = true;
    refetchPending = false;
    await app.click('[aria-label="Refetch available models"]');
    assert.match(app.host.textContent, /OmniRoute is unavailable/);
    assert.match(app.host.textContent, /New upstream model/, 'failed refetch preserves the previous good catalog');
    await app.click('[aria-label="Close model picker"]');
    await app.click('[aria-label^="Change model"]');
    assert.equal(modelGets().length, 3, 'reopening after a failed refetch does not issue another request');
    assert.match(app.host.textContent, /New upstream model/);
  } finally { await app.close(); }
});

test('an empty successful catalog is loaded and reused until explicit Refetch', async () => {
  const paths = [];
  const app = await mountedApp(async path => {
    paths.push(path);
    return path.startsWith('/api/models') ? json({ models: [], model: 'shared-model' }) : defaultResponse(path);
  });
  try {
    for (let index = 0; index < 3; index++) {
      await app.click('[aria-label^="Change model"]');
      assert.match(app.host.textContent, /No models are available/);
      assert.doesNotMatch(app.host.textContent, /Loading models/);
      await app.click('[aria-label="Close model picker"]');
    }
    assert.deepEqual(paths.filter(path => path.startsWith('/api/models')), ['/api/models']);
    await app.click('[aria-label^="Change model"]');
    await app.click('[aria-label="Refetch available models"]');
    assert.deepEqual(paths.filter(path => path.startsWith('/api/models')), ['/api/models', '/api/models?refresh=1']);
  } finally { await app.close(); }
});

test('failed initial fetch requires explicit Refetch, and the first shared request aborts on app unmount', async () => {
  const paths = [];
  let valid = false;
  const app = await mountedApp(async path => {
    paths.push(path);
    if (path.startsWith('/api/models')) return valid ? json({ models: [] }) : json({ error: 'Sign in to OmniRoute.' }, 401);
    return defaultResponse(path);
  });
  try {
    await app.click('[aria-label^="Change model"]');
    assert.match(app.host.textContent, /Sign in to OmniRoute/);
    await app.click('[aria-label="Close model picker"]');
    await app.click('[aria-label^="Change model"]');
    assert.equal(paths.filter(path => path.startsWith('/api/models')).length, 1);
    valid = true;
    await app.click('[aria-label="Refetch available models"]');
    assert.doesNotMatch(app.host.textContent, /Sign in to OmniRoute/);
    assert.match(app.host.textContent, /No models are available/);
  } finally { await app.close(); }
  let signal;
  let finish;
  const pending = await mountedApp(async (path, options = {}) => {
    if (path === '/api/models') { signal = options.signal; return new Promise(resolve => { finish = () => resolve(json({ models: [] })); }); }
    return defaultResponse(path);
  });
  await pending.click('[aria-label^="Change model"]');
  assert.match(pending.host.textContent, /Loading models/);
  assert.equal(signal.aborted, false);
  await pending.close();
  assert.equal(signal.aborted, true);
  finish();
  await flush();
});

for (const initial of [
  { title: 'starting worker', status: 503, data: { starting: true, error: 'Preparing your user workspace…' }, retryWhenReady: true },
  { title: 'authentication failure', status: 401, data: { error: 'Sign in to OmniRoute.' }, retryWhenReady: false },
  { title: 'network failure', status: 503, data: { error: 'OmniRoute network is unavailable.' }, retryWhenReady: false },
]) {
  test(`${initial.title} ${initial.retryWhenReady ? 'gets its first catalog read' : 'does not refetch its catalog'} when the workspace becomes ready`, async () => {
    const realSetInterval = globalThis.setInterval;
    const realClearInterval = globalThis.clearInterval;
    const healthTimers = new Map();
    globalThis.setInterval = (callback, delay, ...args) => {
      if (delay !== 2000) return realSetInterval(callback, delay, ...args);
      const handle = {};
      healthTimers.set(handle, callback);
      return handle;
    };
    globalThis.clearInterval = handle => healthTimers.has(handle) ? healthTimers.delete(handle) : realClearInterval(handle);
    let ready = false;
    const paths = [];
    const app = await mountedApp(async path => {
      paths.push(path);
      if (path === '/api/health') return json({ busy: false, starting: !ready });
      if (path === '/api/models') return ready ? json({ models: [{ id: 'ready-model', name: 'Ready stored model' }] }) : json(initial.data, initial.status);
      return defaultResponse(path);
    });
    try {
      await app.click('[aria-label^="Change model"]');
      assert.equal(paths.filter(path => path.startsWith('/api/models')).length, 1);
      assert.ok(healthTimers.size > 0);
      if (initial.retryWhenReady) assert.match(app.host.textContent, /Loading models/);
      else assert.ok(app.host.textContent.includes(initial.data.error));
      ready = true;
      await React.act(async () => { await Promise.all([...healthTimers.values()].map(callback => callback())); });
      await flush();
      const expectedPaths = initial.retryWhenReady ? ['/api/models', '/api/models'] : ['/api/models'];
      assert.deepEqual(paths.filter(path => path.startsWith('/api/models')), expectedPaths);
      if (initial.retryWhenReady) {
        assert.match(app.host.textContent, /Ready stored model/);
        assert.doesNotMatch(app.host.textContent, /Loading models/);
      } else assert.ok(app.host.textContent.includes(initial.data.error));
      await app.click('[aria-label="Close model picker"]');
      await app.click('[aria-label^="Change model"]');
      await app.click(button => button.textContent === 'Refresh workspace');
      assert.deepEqual(paths.filter(path => path.startsWith('/api/models')), expectedPaths);
    } finally {
      await app.close();
      globalThis.setInterval = realSetInterval;
      globalThis.clearInterval = realClearInterval;
    }
  });
}
