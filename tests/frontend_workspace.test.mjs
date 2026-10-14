import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { currentToolActivities, latestPlan, mergeWorkspaceEvents, runningToolActivities, subagentReports, subagentToolActivities } from '../frontend/src/workspaceActivity.js';

const frontendRequire = createRequire(new URL('../frontend/package.json', import.meta.url));
const serviceRequire = createRequire(new URL('../services/omniroute/package.json', import.meta.url));
const { JSDOM } = serviceRequire('jsdom');
const { transformSync } = serviceRequire('esbuild');
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://127.0.0.1' });
globalThis.window = dom.window;
globalThis.document = dom.window.document;
globalThis.localStorage = dom.window.localStorage;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
dom.window.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
dom.window.HTMLDialogElement.prototype.close = function () { this.open = false; };
dom.window.HTMLElement.prototype.scrollTo = () => {};
dom.window.HTMLElement.prototype.scrollIntoView = () => {};
dom.window.matchMedia = () => ({ matches: true });
const React = frontendRequire('react');
const { createRoot } = frontendRequire('react-dom/client');
const { renderToStaticMarkup } = frontendRequire('react-dom/server');
let apiHandler;
const cache = new Map();
function loadSource(path) {
  if (cache.has(path)) return cache.get(path).exports;
  const module = { exports: {} };
  cache.set(path, module);
  const code = transformSync(readFileSync(path, 'utf8'), { loader: path.endsWith('.jsx') ? 'jsx' : 'js', format: 'cjs' }).code;
  const require = name => {
    if (name.endsWith('.css')) return undefined;
    if (!name.startsWith('.')) return frontendRequire(name);
    if (name === '../api' || name === './api') return { apiFetch: (...args) => apiHandler(...args) };
    const absolute = resolve(dirname(path), name);
    return loadSource(existsSync(`${absolute}.jsx`) ? `${absolute}.jsx` : existsSync(`${absolute}.js`) ? `${absolute}.js` : absolute);
  };
  new Function('require', 'module', 'exports', code)(require, module, module.exports);
  return module.exports;
}
const component = name => loadSource(resolve(fileURLToPath(new URL('../frontend/src/components/', import.meta.url)), `${name}.jsx`)).default;
const ProjectInstructions = component('ProjectInstructions');
const AgentHud = component('AgentHud');
const WorkspaceSidebar = component('WorkspaceSidebar');
const ToolActivity = component('ToolActivity');
const App = loadSource(resolve(fileURLToPath(new URL('../frontend/src/App.jsx', import.meta.url)))).default;
const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'content-type': 'application/json' } });
const flush = async () => { await React.act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); }); };
async function mountedInstructions(handler, props = {}) {
  apiHandler = handler;
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  await React.act(async () => { root.render(React.createElement(React.StrictMode, null, React.createElement(ProjectInstructions, { onClose: () => {}, ...props }))); });
  await flush();
  return {
    host,
    click: async text => { await React.act(async () => { const button = [...host.querySelectorAll('button')].find(button => button.textContent.includes(text)); assert.ok(button); button.click(); }); await flush(); },
    input: async text => { await React.act(async () => { const field = host.querySelector('textarea'); Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set.call(field, text); field.dispatchEvent(new window.Event('input', { bubbles: true })); }); await flush(); },
    close: async () => { await React.act(async () => { root.unmount(); }); host.remove(); },
  };
}

test('saved and streamed activity merge without duplicates or losing a newer completion', () => {
  const started = { kind: 'subagent.started', turn_id: 'parent', timestamp: 10, payload: { subagent: { agent_id: 'worker', role: 'tester', task: 'Read', status: 'running' } } };
  const saved = { id: 'db-id', ...started, payload: undefined, payload_json: JSON.stringify(started.payload) };
  const completed = { kind: 'subagent.completed', turn_id: 'parent', timestamp: 12, payload: { subagent: { ...started.payload.subagent, status: 'completed' }, result: 'Verified report.', duration_ms: 2000 } };
  const merged = mergeWorkspaceEvents([started, completed], [saved]);
  assert.equal(merged.length, 2);
  const reports = subagentReports(merged);
  assert.equal(reports.length, 1);
  assert.equal(reports[0].status, 'completed');
  assert.equal(reports[0].summary, 'Verified report.');
});

test('child commands preserve actual IDs, arguments and error results without requested-call fake success', () => {
  const report = { activities: [
    { kind: 'tool.requested', payload: { name: 'read_file', call_id: 'read-1', arguments: { file_path: 'a' } } },
    { kind: 'tool.started', payload: { name: 'read_file', call_id: 'read-1', arguments: { file_path: 'a' } } },
    { kind: 'tool.failed', payload: { name: 'read_file', call_id: 'read-1', content: 'Missing file', is_error: true } },
  ] };
  const activities = subagentToolActivities(report);
  assert.equal(activities.length, 1);
  assert.equal(activities[0].id, 'read-1');
  assert.equal(activities[0].status, 'failed');
  assert.deepEqual(activities[0].arguments, { file_path: 'a' });
  assert.equal(activities[0].output, 'Missing file');
  assert.deepEqual(subagentToolActivities({ activities: report.activities.slice(0, 1) }), []);
});

test('failed lifecycle stays authoritative over a legacy returned report and child plans stay separate', () => {
  const events = [
    { kind: 'turn.started', timestamp: 1, payload: {} },
    { kind: 'plan.created', timestamp: 2, payload: { goal: 'Parent task', tasks: [{ id: 'parent', title: 'Read', state: 'running' }] } },
    { kind: 'subagent.updated', timestamp: 3, payload: { subagent: { agent_id: 'worker', role: 'tester', task: 'Inspect', status: 'running' }, activity: { kind: 'plan.created', payload: { tasks: [{ id: 'child', title: 'Child work' }] } } } },
    { kind: 'subagent.failed', timestamp: 4, payload: { subagent: { agent_id: 'worker', role: 'tester', task: 'Inspect', status: 'failed' }, error: 'Provider unavailable' } },
  ];
  const agents = subagentReports(events, [{ name: 'spawn_subagent', output: JSON.stringify({ agent_id: 'worker', role: 'tester', task: 'Inspect', summary: 'Old report' }) }]);
  assert.equal(agents[0].status, 'failed');
  assert.equal(latestPlan(events).tasks[0].id, 'parent');
  assert.equal(latestPlan([...events, { kind: 'turn.started', timestamp: 5, payload: {} }]).tasks.length, 0);
  assert.deepEqual(currentToolActivities([{ role: 'agent', tools: [{ name: 'old' }] }, { role: 'agent', content: 'New reply.' }]), []);
});

test('missing file saves use a null digest and conflict reload preserves the draft for review', async () => {
  const requests = [];
  let getCount = 0;
  const editor = await mountedInstructions(async (path, options = {}) => {
    requests.push({ path, options });
    if (options.method === 'POST') return json({ error: 'Instructions changed outside this editor.' }, 409);
    getCount += 1;
    return json(getCount <= 2 ? { exists: false, digest: null, content: '', max_bytes: 65536 }
      : { exists: true, digest: 'latest', content: 'Saved by another editor', max_bytes: 65536 });
  });
  try {
    await editor.input('Keep this unsaved draft');
    await editor.click('Save instructions');
    const save = requests.find(request => request.options.method === 'POST');
    assert.deepEqual(JSON.parse(save.options.body), { content: 'Keep this unsaved draft', expected_digest: null });
    assert.equal(editor.host.querySelector('textarea').value, 'Keep this unsaved draft');
    assert.match(editor.host.textContent, /Instructions changed outside/);
    await editor.click('Reload saved instructions');
    assert.equal(editor.host.querySelector('textarea').value, 'Keep this unsaved draft');
    assert.match(editor.host.textContent, /Saved by another editor/);
    assert.equal(requests[0].options.signal.aborted, true, 'StrictMode cleanup aborts the first load');
  } finally { await editor.close(); }
});

test('instruction load and save are aborted on unmount and editing remains disabled while a task runs', async () => {
  let saveRequest;
  const editor = await mountedInstructions(async (path, options = {}) => {
    if (options.method === 'POST') { saveRequest = options; return new Promise(() => {}); }
    return json({ exists: true, digest: 'original', content: 'Original instructions', max_bytes: 65536 });
  });
  await editor.input('New draft');
  await editor.click('Save instructions');
  assert.ok(saveRequest);
  await editor.close();
  assert.equal(saveRequest.signal.aborted, true);
  const running = await mountedInstructions(async () => json({ exists: true, content: 'Existing instructions' }), { isExecuting: true });
  try {
    assert.equal(running.host.querySelector('textarea').disabled, true);
    const save = [...running.host.querySelectorAll('button')].find(button => button.textContent.includes('Save instructions'));
    assert.equal(save.disabled, true);
  } finally { await running.close(); }
});

test('workspace has named navigation and real detail tabs, with the new assistant mark', () => {
  const sidebar = renderToStaticMarkup(React.createElement(WorkspaceSidebar, { sessions: [{ session_id: 'one', title: 'Saved chat' }], userProfile: 'user', activeTab: 'arena' }));
  assert.match(sidebar, /Workspace navigation|Project instructions|kratos\.md|Saved chat/);
  assert.match(sidebar, /kratos-mark/);
  const details = renderToStaticMarkup(React.createElement(AgentHud, { isOpen: true, events: [], activities: [] }));
  assert.match(details, /Task detail sections|Commands|Subagents|Task/);
  assert.match(details, /No commands yet/);
  assert.doesNotMatch(details, /Thinking capacity|private thought/);
});

test('focused chat hides previous chats at every width and opens task details inside the conversation', async () => {
  const requests = [];
  apiHandler = async path => {
    requests.push(path);
    if (path === '/api/health') return json({ busy: false });
    if (path === '/api/sessions') return json([{ session_id: 'one', title: 'Previous work' }]);
    return json(path === '/api/tools' || path.startsWith('/api/events') ? [] : {});
  };
  const host = document.createElement('div'); document.body.append(host);
  const root = createRoot(host);
  try {
    await React.act(async () => { root.render(React.createElement(App)); }); await flush();
    const shell = host.querySelector('.workspace-shell');
    const sidebar = host.querySelector('.workspace-sidebar');
    assert.equal(shell.classList.contains('focused-chat'), true);
    assert.equal(sidebar.hidden, true);
    assert.equal(host.querySelector('.task-details'), null, 'desktop media query must not force a right rail');
    await React.act(async () => { host.querySelector('[aria-label="Show chats"]').click(); }); await flush();
    assert.equal(sidebar.hidden, false);
    assert.equal(shell.classList.contains('has-chats'), true);
    assert.match(sidebar.textContent, /Previous work/);
    await React.act(async () => { host.querySelector('[aria-label="Close navigation"]').click(); }); await flush();
    assert.equal(sidebar.hidden, true);
    assert.equal(shell.classList.contains('has-chats'), false);
    await React.act(async () => { host.querySelector('[aria-label="Toggle task details"]').click(); }); await flush();
    assert.ok(host.querySelector('.chat-panel > .task-details-inline'), 'details are inline in the chat panel');
    assert.equal(host.querySelector('.workspace-shell > .task-details'), null);
    assert.equal(host.querySelector('.details-backdrop'), null);
    await React.act(async () => { host.querySelector('[aria-label="Close task details"]').click(); }); await flush();
    assert.equal(host.querySelector('.task-details'), null);
    assert.equal(requests.filter(path => path === '/api/models').length, 1, 'layout toggles reuse the catalog');
  } finally { await React.act(async () => { root.unmount(); }); host.remove(); }
});

test('expandable group preserves call identity and expansion while parallel results and cancellation arrive', async () => {
  const host = document.createElement('div'); document.body.append(host);
  const root = createRoot(host);
  const first = { id: 'first', name: 'run_terminal_command', status: 'running', arguments: { command: 'first' } };
  const second = { id: 'second', name: 'run_terminal_command', status: 'running', arguments: { command: 'second' }, source_agent: { agent_id: 'worker', role: 'tester' } };
  const render = async activities => {
    await React.act(async () => { root.render(React.createElement(ToolActivity, { activities, anchors: { first: 'first-anchor', second: 'second-anchor' } })); }); await flush();
  };
  try {
    await render([first]);
    const group = host.querySelector('.tool-activity-group');
    const call = host.querySelector('#first-anchor .tool-card');
    assert.equal(group.open, false);
    assert.match(group.querySelector(':scope > summary').textContent, /1 tool call.*1 running/);
    await React.act(async () => { group.querySelector('summary').click(); }); await flush();
    await React.act(async () => { call.querySelector('summary').click(); }); await flush();
    await render([first, second]);
    assert.equal(host.querySelector('.tool-activity-group'), group);
    assert.equal(host.querySelector('#first-anchor .tool-card'), call);
    assert.equal(group.open, true);
    assert.equal(call.open, true);
    assert.match(group.querySelector(':scope > summary').textContent, /2 tool calls.*2 running/);
    await render([{ ...first, status: 'completed', output: 'First evidence' }, second]);
    assert.equal(host.querySelector('#first-anchor .tool-card'), call);
    assert.equal(call.open, true, 'open argument/result view stays expanded on completion');
    assert.match(call.textContent, /First evidence/);
    assert.match(group.querySelector(':scope > summary').textContent, /1 running/);
    assert.match(host.querySelector('.tool-agent-label').textContent, /tester/);
    await render([{ ...first, status: 'completed', output: 'First evidence' }, { ...second, status: 'cancelled' }]);
    assert.match(group.querySelector(':scope > summary').textContent, /1 stopped/);
    assert.deepEqual([...host.querySelectorAll('.tool-state')].map(node => node.textContent), ['Completed', 'Stopped']);
    await React.act(async () => { group.querySelector('summary').click(); }); await flush();
    assert.equal(group.open, false);
    await render([{ ...first, status: 'completed' }, { ...second, status: 'completed', output: 'Second evidence' }]);
    assert.equal(group.open, false, 'completion does not force open a user-collapsed group');
    assert.match(group.querySelector(':scope > summary').textContent, /Completed/);
  } finally { await React.act(async () => { root.unmount(); }); host.remove(); }
});

test('resuming saved tools_used restores chronological cards, actor ownership and interrupted evidence once', async () => {
  const requests = [];
  const sessions = [{ session_id: 'saved-timeline', title: 'Saved timeline' }, { session_id: 'saved-interrupted', title: 'Saved interrupted' }];
  apiHandler = async (path) => {
    requests.push(path);
    if (path === '/api/health') return json({ busy: false });
    if (path === '/api/sessions') return json(sessions);
    if (path === '/api/sessions/saved-timeline') return json({ session_id: 'saved-timeline', turns: [{
      user: 'Inspect the project', agent: 'Saved final report. [[speak]]Duplicate spoken report.[[/speak]]', status: 'completed', tools_used: [
        { call_id: 'read-1', name: 'read_file', display_prose_before: 'Checking the source.', output: 'Actual source evidence.', status: 'completed' },
        { call_id: 'read-2', name: 'read_file', display_prose_before: 'Now inspecting the imports.', output: 'Missing import.', status: 'failed', is_error: true },
        { call_id: 'subagent:worker-one:read-child', name: 'read_file', source_agent: 'worker-one', agent_role: 'tester', output: 'Actual child evidence.', status: 'completed' },
      ],
    }] });
    if (path === '/api/sessions/saved-interrupted') return json({ session_id: 'saved-interrupted', turns: [{
      user: 'Run the checks', agent: '', status: 'paused', tools_used: [{ call_id: 'check-1', name: 'run_command', arguments: { command: 'npm test' }, status: 'cancelled', status_detail: 'The turn ended before a tool result was recorded.' }],
    }] });
    return json(path === '/api/tools' || path.startsWith('/api/events') ? [] : {});
  };
  const host = document.createElement('div'); document.body.append(host);
  const root = createRoot(host);
  const resume = async title => {
    await React.act(async () => { host.querySelector('[aria-label="Show chats"]').click(); });
    await React.act(async () => { host.querySelector(`.sidebar-session-list button[title="${title}"]`).click(); });
    await flush();
  };
  try {
    await React.act(async () => { root.render(React.createElement(App)); });
    await flush();
    await resume('Saved timeline');
    const blocks = [...host.querySelectorAll('.conversation-stream .message-timeline')].at(-1).children;
    assert.deepEqual([...blocks].map(block => block.classList.contains('tool-activity-group') ? 'tools' : 'text'), ['text', 'tools', 'text', 'tools', 'text']);
    const conversation = host.querySelector('.conversation-stream');
    assert.equal(conversation.querySelectorAll('.tool-card').length, 3);
    assert.match(conversation.querySelector('.tool-agent-label').textContent, /tester/);
    assert.match(conversation.textContent, /Actual source evidence|Actual child evidence|Missing import/);
    assert.equal((conversation.textContent.match(/Saved final report/g) || []).length, 1);
    assert.doesNotMatch(conversation.textContent, /Duplicate spoken report/);
    assert.deepEqual([...conversation.querySelectorAll('.tool-state')].map(node => node.textContent), ['Completed', 'Failed', 'Completed']);
    assert.ok(host.querySelector('[id="tool-1-worker-one%3Aread-child"]'));
    assert.equal(host.querySelectorAll('.task-details .tool-card').length, 0);
    await resume('Saved interrupted');
    assert.equal(host.querySelectorAll('.conversation-stream .tool-card').length, 1);
    assert.match(host.querySelector('.conversation-stream').textContent, /Stopped|before a tool result/);
    assert.doesNotMatch(host.querySelector('.conversation-stream').textContent, /Saved final report/);
    assert.equal(host.querySelector('[aria-label="Running tools"]'), null);
    assert.equal(requests.filter(path => path === '/api/models').length, 1, 'restoring sessions reuses the catalog');
  } finally { await React.act(async () => { root.unmount(); }); host.remove(); }
});

test('real scoped SSE activity reaches the subagent panel without entering the parent answer or refetching models', async () => {
  const requests = [];
  const identity = { agent_id: 'worker-one', role: 'tester', task: 'Inspect README' };
  let failCreation = false;
  const createdModels = [];
  const event = (kind, payload, timestamp) => ({ type: 'runtime_event', event: { kind, payload, turn_id: 'parent-turn', timestamp } });
  apiHandler = async (path, options = {}) => {
    requests.push(path);
    if (path === '/api/health') return json({ busy: false });
    if (path === '/api/models') return json({ model: 'selected-model', models: [{ id: 'selected-model', is_configured: true }] });
    if (path === '/api/telemetry') return json({ model: 'selected-model' });
    if (path === '/api/sessions' && options.method === 'POST') {
      createdModels.push(JSON.parse(options.body).model);
      return failCreation ? json({ error: 'A task is already running.' }, 409) : json({ session_id: 'new-session' }, 201);
    }
    if (path === '/api/chat') {
      assert.equal(JSON.parse(options.body).session_id, 'new-session', 'first send binds the new session before execution');
      const messages = [
        { type: 'start', session_id: 'new-session', model: 'selected-model' },
        event('turn.started', {}, 1),
        event('subagent.started', { subagent: { ...identity, status: 'running' } }, 2),
        event('subagent.updated', { subagent: { ...identity, status: 'running' }, activity: { kind: 'tool.started', payload: { name: 'read_file', call_id: 'child-read', arguments: { file_path: 'README.md' } } } }, 3),
        event('subagent.updated', { subagent: { ...identity, status: 'running' }, activity: { kind: 'tool.completed', payload: { name: 'read_file', call_id: 'child-read', content: 'Actual README evidence' } } }, 4),
        event('subagent.completed', { subagent: { ...identity, status: 'completed' }, result: 'Verified subagent finding.', duration_ms: 100 }, 5),
        { type: 'done', status: 'completed', result: 'Parent final answer.' },
      ];
      return new Response(messages.map(message => `data: ${JSON.stringify(message)}\n\n`).join(''), { headers: { 'content-type': 'text/event-stream' } });
    }
    return json(['/api/tools', '/api/sessions'].includes(path) || path.startsWith('/api/events') ? [] : {});
  };
  const host = document.createElement('div'); document.body.append(host);
  const root = createRoot(host);
  try {
    await React.act(async () => { root.render(React.createElement(App)); });
    await flush();
    await React.act(async () => {
      const field = host.querySelector('textarea[aria-label="Task instruction"]');
      Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set.call(field, 'Inspect the README with a subagent');
      field.dispatchEvent(new window.Event('input', { bubbles: true }));
    });
    await React.act(async () => { [...host.querySelectorAll('button')].find(button => button.textContent === 'Send').click(); });
    await flush();
    assert.match(host.querySelector('.conversation-stream').textContent, /Parent final answer/);
    assert.doesNotMatch([...host.querySelectorAll('.conversation-stream .prose')].map(node => node.textContent).join(''), /Verified subagent finding|Actual README evidence/);
    assert.equal(host.querySelectorAll('.conversation-stream .tool-card').length, 1, 'child command appears once at its actual chat anchor');
    assert.equal(host.querySelector('.task-details'), null, 'details stay hidden until requested');
    await React.act(async () => { host.querySelector('[aria-label="Toggle task details"]').click(); });
    await React.act(async () => { host.querySelector('#details-tab-subagents').click(); });
    assert.match(host.querySelector('.task-details').textContent, /Verified subagent finding/);
    assert.equal(host.querySelectorAll('.subagent-card').length, 1);
    assert.match(host.querySelector('.task-details').textContent, /read_file/);
    assert.match(host.querySelector('.task-details').textContent, /Completed/);
    assert.equal(host.querySelectorAll('.task-details .tool-card').length, 0, 'details link to commands instead of duplicating cards');
    assert.equal(requests.filter(path => path === '/api/models').length, 1);
    assert.deepEqual(createdModels, ['selected-model']);
    failCreation = true;
    await React.act(async () => {
      const newChat = host.querySelector('[aria-label="New chat"]');
      newChat.click(); newChat.click();
    });
    await flush();
    assert.equal(createdModels.length, 2, 'two clicks share one creation request');
    assert.match(host.querySelector('.conversation-stream').textContent, /Parent final answer/, 'creation failure keeps existing chat');
    assert.match(host.textContent, /A task is already running/);
    failCreation = false;
    await React.act(async () => { host.querySelector('[aria-label="New chat"]').click(); });
    await flush();
    assert.doesNotMatch(host.querySelector('.conversation-stream').textContent, /Parent final answer/);
    assert.match(host.querySelector('.conversation-stream').textContent, /What are we working on/);
    assert.equal(requests.filter(path => path === '/api/models').length, 1, 'new chats reuse model catalog');
  } finally { await React.act(async () => { root.unmount(); }); host.remove(); }
});

test('tool invocation is visibly running before its held result and another parallel completion cannot hide it', async () => {
  let controller;
  const stream = new ReadableStream({ start(value) { controller = value; } });
  apiHandler = async (path, options = {}) => {
    if (path === '/api/health') return json({ busy: false });
    if (path === '/api/sessions' && options.method === 'POST') return json({ session_id: 'running-session' }, 201);
    if (path === '/api/chat') return new Response(stream, { headers: { 'content-type': 'text/event-stream' } });
    return json(['/api/tools', '/api/sessions'].includes(path) || path.startsWith('/api/events') ? [] : {});
  };
  const host = document.createElement('div'); document.body.append(host);
  const root = createRoot(host);
  const frame = async data => {
    await React.act(async () => { controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(data)}\n\n`)); });
    await flush();
  };
  try {
    await React.act(async () => { root.render(React.createElement(App)); }); await flush();
    await React.act(async () => { [...host.querySelectorAll('button')].find(button => button.textContent.includes('Explore a project')).click(); });
    await React.act(async () => { [...host.querySelectorAll('button')].find(button => button.textContent === 'Send').click(); }); await flush();
    await frame({ type: 'token', token: 'I will inspect the README.\n\n' });
    await frame({ type: 'tool_call', tool_call: { name: 'read_file', call_id: 'read-one', args: { file_path: 'README.md' } } });
    const liveCard = host.querySelector('.conversation-stream .tool-running');
    assert.ok(liveCard, 'invocation exists immediately while result is still held');
    const firstGroup = liveCard.closest('.tool-activity-group');
    assert.equal(firstGroup.open, false, 'tool details start compact');
    assert.match(firstGroup.querySelector('summary').textContent, /1 tool call.*1 running/);
    await React.act(async () => { firstGroup.querySelector('summary').click(); }); await flush();
    await React.act(async () => { liveCard.querySelector('summary').click(); }); await flush();
    assert.equal(liveCard.open, true);
    await React.act(async () => { host.querySelector('[aria-label="Toggle task details"]').click(); });
    assert.match(liveCard.textContent, /Running|README\.md|Waiting for the tool/);
    assert.equal(host.querySelector('[aria-label="Stop task"]').disabled, false);
    assert.match(host.querySelector('.task-details .details-command-summary').textContent, /read_file|Running/);
    assert.equal(host.querySelectorAll('.task-details .tool-card').length, 0);
    assert.match(host.querySelector('[aria-label="Running tools"]').textContent, /1 tool is running/);
    assert.doesNotMatch(host.querySelector('[aria-label="Running tools"]').textContent, /read_file/);
    const conversation = host.querySelector('.conversation-stream');
    Object.defineProperties(conversation, { scrollHeight: { configurable: true, value: 1000 }, clientHeight: { configurable: true, value: 200 } });
    conversation.scrollTop = 0;
    conversation.dispatchEvent(new window.Event('scroll', { bubbles: true }));
    const scrollCalls = [];
    conversation.scrollTo = value => scrollCalls.push(value);
    await frame({ type: 'token', token: 'I will check the directory next.\n\n' });
    await frame({ type: 'tool_call', tool_call: { name: 'list_directory', call_id: 'list-two', args: { path: '.' } } });
    const blocks = [...host.querySelector('.assistant-message .message-timeline').children];
    assert.match(blocks[0].textContent, /I will inspect the README/);
    assert.match(blocks[1].textContent, /read_file/);
    assert.match(blocks[2].textContent, /I will check the directory next/);
    assert.match(blocks[3].textContent, /list_directory/);
    assert.equal(scrollCalls.length, 0, 'incoming tool does not pull the user away from older messages');
    await frame({ type: 'tool_result', name: 'read_file', call_id: 'read-one', result: 'README evidence' });
    assert.equal(host.querySelector('.timeline-tool .tool-card'), liveCard, 'result updates the same existing card');
    assert.match(host.querySelector('.chat-panel-header').textContent, /list_directory/, 'second invocation remains active when first completes');
    assert.equal(host.querySelector('.conversation-stream .tool-running summary').getAttribute('aria-label'), 'list_directory: Running');
    conversation.scrollTop = 800;
    conversation.dispatchEvent(new window.Event('scroll', { bubbles: true }));
    await frame({ type: 'tool_result', name: 'list_directory', call_id: 'list-two', result: 'Directory evidence' });
    assert.ok(scrollCalls.length > 0, 'near-bottom reader continues following updates');
    assert.equal(host.querySelector('.conversation-stream .tool-running'), null);
    await frame({ type: 'token', token: 'Checked both sources.' });
    await frame({ type: 'done', status: 'completed', result: 'Checked both sources.' });
    await React.act(async () => { controller.close(); }); await flush();
    assert.equal(host.querySelectorAll('.conversation-stream .tool-card').length, 2);
    assert.equal((host.querySelector('.conversation-stream').textContent.match(/Checked both sources\./g) || []).length, 1);
    await React.act(async () => {
      liveCard.open = false;
      firstGroup.open = false;
    }); await flush();
    await React.act(async () => { host.querySelector('.details-command-summary button').click(); });
    await flush();
    assert.equal(firstGroup.open, true, 'Commands jump opens the enclosing collapsed group');
    assert.equal(liveCard.open, true, 'Commands summary opens the existing conversation card');
    assert.equal(document.activeElement, liveCard.querySelector('summary'));
  } finally { await React.act(async () => { root.unmount(); }); host.remove(); }
});

test('live tools include real child invocations and stop showing them when the worker ends', () => {
  const event = status => ({ kind: 'subagent.updated', timestamp: 1, payload: { subagent: { agent_id: 'child', role: 'tester', task: 'Read', status },
    activity: { kind: 'tool.started', payload: { name: 'read_file', call_id: 'real-child-call', arguments: { file_path: 'README.md' } } } } });
  assert.equal(runningToolActivities([], [event('running')])[0].live_id, 'child:real-child-call');
  assert.deepEqual(runningToolActivities([], [event('cancelled')]), []);
  assert.deepEqual(runningToolActivities([], [event('running')], null), [], 'historical worker is not shown before current turn begins');
  assert.deepEqual(runningToolActivities([], [{ ...event('running'), turn_id: 'old-turn' }], 'new-turn'), [], 'old unfinished workers do not appear in a later turn');
});

test('profile vision starts explicitly without speech and voice status waits for a confirmed connection', async () => {
  let status = { runtime_started: false, speech_started: false, speech_enabled: true, speech_backend: 'gemini', video_mode: 'camera', camera_active: false, microphone_active: false, muted: true };
  const controls = [];
  let finishControl;
  apiHandler = async (path, options = {}) => {
    if (path === '/api/health') return json({ busy: false });
    if (path === '/api/live/status') return json(status);
    if (path === '/api/live/control') {
      controls.push(JSON.parse(options.body));
      return new Promise(resolve => { finishControl = (data, code = 200) => { if (code === 200) status = data; resolve(json(data, code)); }; });
    }
    return json(['/api/tools', '/api/sessions'].includes(path) || path.startsWith('/api/events') ? [] : {});
  };
  const host = document.createElement('div'); document.body.append(host);
  const root = createRoot(host);
  try {
    await React.act(async () => { root.render(React.createElement(App)); }); await flush();
    assert.match(host.querySelector('.live-controls').textContent, /Voice OFFLINE/);
    assert.equal(host.querySelector('[title="/vision camera"]').getAttribute('aria-pressed'), 'false');
    await React.act(async () => { host.querySelector('[title="/vision camera"]').click(); }); await flush();
    assert.deepEqual(controls[0], { action: 'set_vision_mode', value: 'camera' });
    assert.match(host.textContent, /Updating capture/);
    assert.equal(host.querySelector('[title="/vision camera"]').disabled, true);
    await React.act(async () => { finishControl({ ...status, runtime_started: true, camera_active: true }); }); await flush();
    assert.equal(host.querySelector('[title="/vision camera"]').getAttribute('aria-pressed'), 'true');
    assert.match(host.querySelector('.live-controls').textContent, /Voice OFFLINE|Muted/);
    await React.act(async () => { host.querySelector('[aria-label="Start voice session"]').click(); }); await flush();
    assert.deepEqual(controls[1], { action: 'reconnect', value: null });
    assert.match(host.querySelector('.live-controls').textContent, /Voice STARTING/);
    await React.act(async () => { finishControl({ ...status, speech_started: true, gemini_connected: false }); }); await flush();
    assert.match(host.querySelector('.live-controls').textContent, /Voice CONNECTING/);
    status = { ...status, gemini_connected: true };
    await React.act(async () => { host.querySelector('[aria-label="Refresh workspace"]').click(); }); await flush();
    assert.match(host.querySelector('.live-controls').textContent, /Voice ONLINE/);
    await React.act(async () => { host.querySelector('[aria-label="Unmute microphone"]').click(); }); await flush();
    await React.act(async () => { finishControl({ error: 'Allow microphone access for desktop apps in Windows Settings.' }, 503); }); await flush();
    assert.match(host.querySelector('.live-controls').textContent, /Windows Settings/);
    assert.match(host.querySelector('.live-controls').textContent, /Voice ONLINE|Muted/);
    assert.doesNotMatch(host.querySelector('.live-controls').textContent, /Mic on/);
  } finally { await React.act(async () => { root.unmount(); }); host.remove(); }
});
