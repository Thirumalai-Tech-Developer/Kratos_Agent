import { updateToolActivity } from './chatActivity.js';

function parsed(value) {
  if (typeof value !== 'string') return value && typeof value === 'object' ? value : {};
  try { return JSON.parse(value); } catch { return {}; }
}
export function eventPayload(event) { return parsed(event?.payload ?? event?.payload_json); }
export function sortedEvents(events = []) {
  return (Array.isArray(events) ? events : []).filter(event => event && typeof event === 'object')
    .map((event, index) => ({ ...event, sequence: index }))
    .sort((a, b) => Number(a.ts ?? a.timestamp ?? a.sequence) - Number(b.ts ?? b.timestamp ?? b.sequence));
}
export function mergeWorkspaceEvents(previous = [], incoming = []) {
  const merged = new Map();
  for (const event of sortedEvents([...previous, ...(Array.isArray(incoming) ? incoming : [])])) {
    const payload = eventPayload(event);
    const timestamp = event.ts ?? event.timestamp;
    // SSE and saved rows share the original timestamp and turn ID, but only
    // the saved row has a database ID. Match their runtime identity instead.
    const key = timestamp == null ? event.id || JSON.stringify([event.kind, event.turn_id, payload])
      : JSON.stringify([Number(timestamp), event.kind, event.turn_id || '',
        payload.subagent?.agent_id || payload.subagent?.id || '', payload.activity?.kind || '',
        payload.call_id || payload.id || payload.task_id || '']);
    merged.set(key, { ...merged.get(key), ...event, payload });
  }
  return sortedEvents([...merged.values()]);
}
export function latestPlan(events = []) {
  let plan = null;
  const tasks = new Map();
  for (const event of sortedEvents(events)) {
    const payload = eventPayload(event);
    if (payload.subagent) continue;
    if (event.kind === 'turn.started') { plan = null; tasks.clear(); }
    const candidate = payload.plan || (Array.isArray(payload.tasks) ? payload : null);
    if (candidate && Array.isArray(candidate.tasks)) {
      plan = candidate;
      tasks.clear();
      for (const task of candidate.tasks) tasks.set(task.id || task.task_id || task.title, task);
    }
    if (event.kind?.startsWith('task.') && (payload.id || payload.task_id)) {
      const id = payload.id || payload.task_id;
      tasks.set(id, { ...tasks.get(id), ...payload });
    }
  }
  return { ...(plan || {}), tasks: [...tasks.values()] };
}
export function subagentReports(events = [], activities = []) {
  const reports = new Map();
  const upsert = (record, fallbackId) => {
    if (!record || typeof record !== 'object') return;
    const id = record.agent_id || record.id || fallbackId;
    if (!id || (!record.role && !record.task && !reports.has(id))) return;
    reports.set(id, { ...reports.get(id), ...record, id, activities: reports.get(id)?.activities || [] });
  };
  for (const event of sortedEvents(events)) {
    const payload = eventPayload(event);
    const scope = payload.subagent;
    const scopedId = scope?.agent_id || scope?.id;
    if (!scopedId) continue;
    upsert(scope, scopedId);
    const report = reports.get(scopedId);
    if (!report) continue;
    if (typeof payload.summary === 'string') report.summary = payload.summary;
    if (typeof payload.report === 'string') report.summary = payload.report;
    if (typeof payload.result === 'string') report.summary = payload.result;
    else if (typeof payload.result?.summary === 'string') report.summary = payload.result.summary;
    if (typeof payload.duration_ms === 'number') report.duration_ms = payload.duration_ms;
    if (payload.error) report.error = payload.error;
    if (payload.activity && /^(?:tool|command|file)\./.test(payload.activity.kind || '')) report.activities.push({ ...payload.activity, ts: event.ts ?? event.timestamp });
    if (/^(?:tool|command|file)\./.test(event.kind || '')) report.activities.push(event);
  }
  for (const activity of activities) {
    if (!['spawn_subagent', 'spawn_parallel_subagents'].includes(activity.name)) continue;
    const output = parsed(activity.output);
    const records = Array.isArray(output) ? output : Array.isArray(output.results) ? output.results : output.agent_id ? [output] : [];
    for (const record of records) {
      if (reports.has(record.agent_id || record.id)) continue;
      upsert({ ...record, status: record.error ? 'failed' : record.status || 'unknown' }, record.agent_id);
    }
    if (activity.status === 'running') {
      const specs = activity.name === 'spawn_subagent' ? [activity.arguments] : activity.arguments?.subagents || [];
      specs.forEach((spec, index) => {
        if (!spec?.role && !spec?.task) return;
        if ([...reports.values()].some(report => report.role === spec.role && report.task === spec.task)) return;
        upsert({ ...spec, status: 'running' }, `${activity.id}-${index}`);
      });
    }
  }
  return [...reports.values()];
}
export function currentToolActivities(messages = []) {
  const latest = [...messages].reverse().find(message => message.role !== 'user');
  return latest?.tools || [];
}
export function subagentToolActivities(report) {
  return (report?.activities || []).filter(event => ['tool.started', 'tool.completed', 'tool.failed'].includes(event.kind)).reduce((activities, event) => {
    const payload = eventPayload(event);
    return updateToolActivity(activities, { ...payload, type: event.kind === 'tool.started' ? 'tool_call' : event.kind === 'tool.failed' ? 'tool_failed' : 'tool_result',
      ...(event.kind === 'tool.started' ? { tool_call: { ...payload, args: payload.arguments } } : {}) });
  }, []);
}
export function runningToolActivities(messages = [], events = [], turnId) {
  const parent = currentToolActivities(messages).filter(tool => tool.status === 'running')
    .map(tool => ({ ...tool, live_id: `parent:${tool.id}` }));
  const scopedEvents = turnId === undefined ? events : turnId ? events.filter(event => event.turn_id === turnId) : [];
  const children = subagentReports(scopedEvents).filter(agent => agent.status === 'running')
    .flatMap(agent => subagentToolActivities(agent).filter(tool => tool.status === 'running')
      .map(tool => ({ ...tool, live_id: `${agent.id}:${tool.id}`, agent_role: agent.role })));
  return [...parent, ...children];
}
