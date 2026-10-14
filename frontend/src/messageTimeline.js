/** Ordered assistant prose and tool calls. Results update their original card. */
import { finishToolActivity, restoredToolActivity, updateToolActivity } from './chatActivity.js';
import { visibleAssistantText } from './speechDirectives.js';

const textValue = value => typeof value === 'string' ? value : '';
const toolBlocks = timeline => timeline.filter(block => block.type === 'tool');
const allText = timeline => timeline.filter(block => block.type === 'text').map(block => block.content).join('');

/** Presentation groups only adjacent calls; saved events remain individually addressable. */
export function groupedMessageTimeline(timeline = []) {
  const groups = [];
  for (const block of timeline) {
    if (block.type !== 'tool') {
      groups.push(block);
      continue;
    }
    const previous = groups.at(-1);
    if (previous?.type === 'tool-group') previous.blocks.push(block);
    else groups.push({ id: `group-${block.id}`, type: 'tool-group', blocks: [block] });
  }
  return groups;
}

function textBlock(timeline, content) {
  let number = 0;
  const used = new Set(timeline.map(block => block.id));
  while (used.has(`text-${number}`)) number += 1;
  return { id: `text-${number}`, type: 'text', content };
}

export function appendTimelineText(timeline = [], delta = '') {
  delta = textValue(delta);
  if (!delta) return timeline;
  const last = timeline.at(-1);
  if (last?.type === 'text') {
    return timeline.map((block, index) => index === timeline.length - 1
      ? { ...block, content: block.content + delta } : block);
  }
  return [...timeline, textBlock(timeline, delta)];
}

function cleanToolEvent(data, starting, activities) {
  const event = data && typeof data === 'object' ? { ...data } : {};
  const call = event.tool_call && typeof event.tool_call === 'object' ? event.tool_call : {};
  const result = event.tool_result && typeof event.tool_result === 'object' ? event.tool_result : {};
  const id = call.call_id || result.call_id || event.call_id || call.id || result.id;
  const previous = id ? activities.find(item => item.id === id) : undefined;
  const name = call.name || result.name || event.name
    || (typeof event.tool_call === 'string' ? event.tool_call : undefined) || previous?.name;
  const agentRole = call.agent_role ?? result.agent_role ?? event.agent_role;
  const sourceAgent = call.source_agent ?? result.source_agent ?? event.source_agent;
  if (event.tool_call === null) delete event.tool_call;
  if (event.tool_result === null) delete event.tool_result;
  // A result need not repeat the tool name. Its stable call ID is sufficient.
  if (name) event.name = name;
  if (id) event.call_id = id;
  if (agentRole !== undefined) event.agent_role = agentRole;
  if (sourceAgent !== undefined) event.source_agent = sourceAgent;
  if (starting) event.type = 'tool_call';
  else {
    event.type = event.type === 'tool_failed' ? 'tool_failed' : 'tool_result';
    delete event.tool_call;
  }
  return event;
}

function updateTimelineTool(timeline, data, starting) {
  const existing = toolBlocks(timeline).map(block => block.activity);
  const event = cleanToolEvent(data, starting, existing);
  const updated = updateToolActivity(existing, event).map(activity => {
    const before = existing.find(item => item.id === activity.id);
    const owned = activity !== before ? {
      ...activity,
      ...(event.agent_role === undefined ? {} : { agent_role: event.agent_role }),
      ...(event.source_agent === undefined ? {} : { source_agent: event.source_agent }),
    } : activity;
    // A replayed start must not erase an already received result.
    return starting && before && before.status !== 'running'
      ? { ...owned, status: before.status } : owned;
  });
  const known = new Set(existing.map(activity => activity.id));
  const byId = new Map(updated.map(activity => [activity.id, activity]));
  const blocks = timeline.map(block => block.type === 'tool'
    ? { ...block, activity: byId.get(block.activity.id) || block.activity } : block);
  return [...blocks, ...updated.filter(activity => !known.has(activity.id)).map(activity => ({
    id: `tool-${activity.id}`, type: 'tool', activity,
  }))];
}

export function timelineToolStart(timeline = [], data = {}) {
  return updateTimelineTool(timeline, data, true);
}

export function resolveTimelineTool(timeline = [], data = {}) {
  return updateTimelineTool(timeline, data, false);
}

export function finishTimelineTools(timeline = [], status) {
  const finished = new Map(finishToolActivity(toolBlocks(timeline).map(block => block.activity), status)
    .map(activity => [activity.id, activity]));
  return timeline.map(block => block.type === 'tool'
    ? { ...block, activity: finished.get(block.activity.id) } : block);
}

export function finishActorTimelineTools(timeline = [], actorId, status) {
  return timeline.map(block => {
    if (block.type !== 'tool') return block;
    const owner = block.activity.source_agent;
    const id = typeof owner === 'object' && owner !== null ? owner.agent_id : owner;
    if (id !== actorId) return block;
    return { ...block, activity: finishToolActivity([block.activity], status)[0] };
  });
}

/** Reconcile an authoritative final answer without moving prose across tools. */
export function finalizeTimelineText(timeline = [], finalText = '') {
  finalText = textValue(finalText);
  if (!finalText) return timeline;
  const combined = allText(timeline);
  if (combined === finalText || visibleAssistantText(combined) === visibleAssistantText(finalText)) return timeline;
  if (combined && finalText.startsWith(combined)) return appendTimelineText(timeline, finalText.slice(combined.length));
  const last = timeline.at(-1);
  if (last?.type === 'text') {
    // The final frame often contains only the last model generation, whereas
    // the token buffer also includes commentary emitted before earlier tools.
    if (last.content === finalText || visibleAssistantText(last.content) === visibleAssistantText(finalText)) return timeline;
    const earlier = allText(timeline.slice(0, -1));
    const tail = earlier && finalText.startsWith(earlier) ? finalText.slice(earlier.length) : finalText;
    return timeline.map((block, index) => index === timeline.length - 1 ? { ...block, content: tail } : block);
  }
  return appendTimelineText(timeline, finalText);
}

/** App supplies cumulative, think-tag-parsed content; only its new suffix appends. */
export function syncTimelineText(timeline = [], previousSnapshot = '', nextSnapshot = '') {
  previousSnapshot = textValue(previousSnapshot);
  nextSnapshot = textValue(nextSnapshot);
  if (nextSnapshot === previousSnapshot) return timeline;
  if (nextSnapshot.startsWith(previousSnapshot)) return appendTimelineText(timeline, nextSnapshot.slice(previousSnapshot.length));
  return finalizeTimelineText(timeline, nextSnapshot);
}

/** Restore saved prose anchors and evidence; older records retain tools→final. */
export function savedMessageTimeline(message = {}) {
  const calls = (Array.isArray(message.tools_used) ? message.tools_used : Array.isArray(message.tool_calls) ? message.tool_calls : [])
    .filter(call => call && typeof call === 'object');
  const activities = restoredToolActivity(calls);
  let timeline = [];
  activities.forEach((activity, index) => {
    // Provider reasoning belongs in its existing separate renderer. It must
    // not leak into the prose that preceded a saved tool invocation.
    const prose = textValue(calls[index].display_prose_before)
      .replace(/<think>[\s\S]*?(?:<\/think>|$)/gi, '');
    if (prose.trim()) timeline = appendTimelineText(timeline, prose);
    timeline.push({ id: `tool-${activity.id}`, type: 'tool', activity });
  });
  const content = message.content ?? message.agent_reply ?? message.agent ?? message.reply ?? message.response;
  return finalizeTimelineText(timeline, content);
}

/** Display existing chronology, or the saved legacy tools and final answer. */
export function messageTimeline(message = {}) {
  const assistant = message.role !== 'user';
  const explicit = Array.isArray(message.timeline) && message.timeline.length > 0;
  let timeline;
  if (explicit) timeline = message.timeline;
  else if (Array.isArray(message.tools_used) || Array.isArray(message.tool_calls)) timeline = savedMessageTimeline(message);
  else {
    // Legacy sessions contain a final answer and a tool list, without text
    // anchors. Preserve that known information; do not fabricate timestamps.
    const activities = Array.isArray(message.tools) ? message.tools : [];
    timeline = activities.map(activity => ({ id: `tool-${activity.id}`, type: 'tool', activity }));
    if (textValue(message.content)) timeline = appendTimelineText(timeline, message.content);
  }
  if (!assistant) return timeline;
  let source = '', visible = '';
  return timeline.flatMap(block => {
    if (block.type !== 'text') return [block];
    source += textValue(block.content);
    const next = visibleAssistantText(source, { trim: false });
    const content = next.startsWith(visible) ? next.slice(visible.length) : next;
    visible = next;
    // Carry speech-marker state across tool boundaries as well as text chunks.
    return content.trim() ? [{ ...block, content }] : [];
  });
}
