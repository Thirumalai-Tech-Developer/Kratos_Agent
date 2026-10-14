import assert from 'node:assert/strict';
import test from 'node:test';
import {
  appendTimelineText, finalizeTimelineText, finishActorTimelineTools, finishTimelineTools, groupedMessageTimeline, messageTimeline,
  resolveTimelineTool, savedMessageTimeline, syncTimelineText, timelineToolStart,
} from '../frontend/src/messageTimeline.js';

const start = (id, name = 'read_file') => ({ type: 'tool_call', call_id: id, name, args: { path: id } });
const result = (id, content = 'Read complete.') => ({ type: 'tool_result', call_id: id, content });
const types = timeline => timeline.map(block => block.type);
const text = timeline => timeline.filter(block => block.type === 'text').map(block => block.content);

test('adjacent tools form one stable group while prose separates different batches', () => {
  let timeline = appendTimelineText([], 'Inspecting the source.');
  timeline = timelineToolStart(timeline, start('first'));
  const firstGroup = groupedMessageTimeline(timeline)[1];
  timeline = timelineToolStart(timeline, start('second'));
  timeline = appendTimelineText(timeline, 'The files share a dependency.');
  timeline = timelineToolStart(timeline, start('third'));
  const grouped = groupedMessageTimeline(timeline);
  assert.deepEqual(types(grouped), ['text', 'tool-group', 'text', 'tool-group']);
  assert.equal(grouped[1].id, firstGroup.id, 'adding a second call preserves the group anchor');
  assert.deepEqual(grouped[1].blocks.map(block => block.activity.id), ['first', 'second']);
  assert.deepEqual(grouped[3].blocks.map(block => block.activity.id), ['third']);
  assert.deepEqual(types(timeline), ['text', 'tool', 'tool', 'text', 'tool'], 'presentation never rewrites saved events');
  assert.equal(grouped[1].blocks[0], timeline[1]);
});

test('text and subsequent tools stay in the order they arrived', () => {
  let timeline = appendTimelineText([], 'I will inspect the project.');
  timeline = timelineToolStart(timeline, start('first'));
  const ids = timeline.map(block => block.id);
  timeline = appendTimelineText(timeline, 'The entry point imports the runtime.');
  timeline = timelineToolStart(timeline, start('second'));
  timeline = appendTimelineText(timeline, 'Its architecture is ');
  timeline = appendTimelineText(timeline, 'shown below.');
  assert.deepEqual(types(timeline), ['text', 'tool', 'text', 'tool', 'text']);
  assert.deepEqual(timeline.slice(0, 2).map(block => block.id), ids);
  assert.deepEqual(text(timeline), ['I will inspect the project.', 'The entry point imports the runtime.', 'Its architecture is shown below.']);
});

test('parallel calls of the same tool resolve by ID in their original positions', () => {
  let timeline = timelineToolStart([], start('a'));
  timeline = timelineToolStart(timeline, start('b'));
  timeline = appendTimelineText(timeline, 'While those reads run, I will examine the plan.');
  const ids = timeline.map(block => block.id);
  timeline = resolveTimelineTool(timeline, result('b', 'Second result.'));
  timeline = resolveTimelineTool(timeline, result('a', 'First result.'));
  assert.deepEqual(timeline.map(block => block.id), ids);
  assert.equal(timeline[0].activity.name, 'read_file');
  assert.equal(timeline[0].activity.output, 'First result.');
  assert.equal(timeline[1].activity.output, 'Second result.');
  assert.deepEqual(timeline.slice(0, 2).map(block => block.activity.status), ['completed', 'completed']);
});

test('replayed starts and repeated results do not add cards or regress completion', () => {
  let timeline = timelineToolStart([], start('a'));
  timeline = resolveTimelineTool(timeline, result('a'));
  timeline = timelineToolStart(timeline, start('a'));
  timeline = resolveTimelineTool(timeline, result('a'));
  assert.equal(timeline.length, 1);
  assert.equal(timeline[0].activity.status, 'completed');
  assert.equal(timeline[0].activity.output, 'Read complete.');
});

test('results received without a start create one truthful completed card', () => {
  let timeline = appendTimelineText([], 'Earlier commentary.');
  timeline = resolveTimelineTool(timeline, { ...result('a'), name: 'read_file', truncated: true });
  timeline = resolveTimelineTool(timeline, result('a'));
  assert.deepEqual(types(timeline), ['text', 'tool']);
  assert.equal(timeline[1].activity.name, 'read_file');
  assert.equal(timeline[1].activity.status, 'completed');
});

test('final answer already streamed is not duplicated after earlier commentary and tools', () => {
  let timeline = appendTimelineText([], 'Checking the source.');
  timeline = timelineToolStart(timeline, start('a'));
  timeline = appendTimelineText(timeline, 'Here is the finished diagram.');
  assert.equal(finalizeTimelineText(timeline, 'Here is the finished diagram.'), timeline);
  assert.equal(finalizeTimelineText(timeline, 'Checking the source.Here is the finished diagram.'), timeline);
});

test('authoritative final content replaces only its streamed partial tail', () => {
  let timeline = appendTimelineText([], 'I am reading the source.');
  timeline = timelineToolStart(timeline, start('a'));
  timeline = appendTimelineText(timeline, 'The archit');
  const updated = finalizeTimelineText(timeline, 'The architecture has three layers.');
  assert.equal(updated[0], timeline[0]);
  assert.equal(updated[1], timeline[1]);
  assert.equal(updated[2].id, timeline[2].id);
  assert.equal(updated[2].content, 'The architecture has three layers.');
});

test('a final answer following a tool appends below the existing card', () => {
  let timeline = appendTimelineText([], 'Reading now.');
  timeline = timelineToolStart(timeline, start('a'));
  timeline = finalizeTimelineText(timeline, 'Finished.');
  assert.deepEqual(types(timeline), ['text', 'tool', 'text']);
  assert.deepEqual(text(timeline), ['Reading now.', 'Finished.']);
});

test('cumulative token snapshots append only new text at the latest anchor', () => {
  let timeline = syncTimelineText([], '', 'First text.');
  timeline = timelineToolStart(timeline, start('a'));
  timeline = syncTimelineText(timeline, 'First text.', 'First text.Second ');
  timeline = syncTimelineText(timeline, 'First text.Second ', 'First text.Second text.');
  assert.deepEqual(types(timeline), ['text', 'tool', 'text']);
  assert.deepEqual(text(timeline), ['First text.', 'Second text.']);
  assert.equal(syncTimelineText(timeline, 'same', 'same'), timeline);
});

test('terminal status changes outstanding tools without moving cards or inventing durations', () => {
  let timeline = timelineToolStart([], start('a'));
  timeline = timelineToolStart(timeline, start('b'));
  timeline = resolveTimelineTool(timeline, result('b'));
  const stopped = finishTimelineTools(timeline, 'cancelled');
  assert.deepEqual(stopped.map(block => block.id), timeline.map(block => block.id));
  assert.deepEqual(stopped.map(block => block.activity.status), ['cancelled', 'completed']);
  assert.equal('duration' in stopped[0].activity, false);
  assert.equal(finishTimelineTools(timeline, 'completed')[0].activity.status, 'unknown');
});

test('speech metadata stays hidden even when markers cross a tool boundary', () => {
  let timeline = appendTimelineText([], 'Visible greeting. [[spe');
  timeline = timelineToolStart(timeline, start('a'));
  timeline = appendTimelineText(timeline, 'ak]]Duplicate spoken greeting.[[/speak]] Visible conclusion.');
  const visible = messageTimeline({ role: 'agent', timeline });
  assert.deepEqual(types(visible), ['text', 'tool', 'text']);
  assert.deepEqual(text(visible).map(content => content.trim()), ['Visible greeting.', 'Visible conclusion.']);
  assert.equal(JSON.stringify(visible).includes('Duplicate spoken'), false);
  assert.equal(JSON.stringify(visible).includes('[[speak]]'), false);
});

test('reasoning is left for its existing separate renderer and user examples remain literal', () => {
  const displayed = messageTimeline({ role: 'agent', content: 'Answer.', reasoning: 'Private reasoning.' });
  assert.deepEqual(text(displayed), ['Answer.']);
  assert.equal(JSON.stringify(displayed).includes('Private reasoning.'), false);
  assert.deepEqual(text(messageTimeline({ role: 'user', content: 'Use [[speak]]hello[[/speak]].' })), ['Use [[speak]]hello[[/speak]].']);
});

test('restored legacy messages show saved calls and final answer without fabricated success', () => {
  const displayed = messageTimeline({ role: 'agent', content: 'Finished.', tool_calls: [
    { call_id: 'a', name: 'read_file', arguments: { path: 'a' } },
    { call_id: 'b', name: 'read_file', result: 'Saved result.' },
  ] });
  assert.deepEqual(types(displayed), ['tool', 'tool', 'text']);
  assert.deepEqual(displayed.slice(0, 2).map(block => block.activity.status), ['unknown', 'completed']);
  assert.deepEqual(text(displayed), ['Finished.']);
  assert.deepEqual(messageTimeline({ role: 'agent', content: '', timeline: [] }), []);
});

test('saved tools_used restores prose anchors, recorded output and truthful terminal states', () => {
  const saved = { role: 'agent', agent: 'Finished report.', tools_used: [
    { call_id: 'read-a', name: 'read_file', arguments: { path: 'a' }, display_prose_before: 'Inspecting the source.\n', output: 'Actual source.', status: 'completed', duration_ms: 120, truncated: true },
    { call_id: 'read-b', name: 'read_file', display_prose_before: 'The entry point imports the runtime.\n', output: 'Cancelled by user', status: 'cancelled', is_error: true },
    { call_id: 'read-c', name: 'read_file', status: 'failed', status_detail: 'The turn ended before a tool result was recorded.' },
  ] };
  const timeline = savedMessageTimeline(saved);
  assert.deepEqual(types(timeline), ['text', 'tool', 'text', 'tool', 'tool', 'text']);
  assert.deepEqual(text(timeline), ['Inspecting the source.\n', 'The entry point imports the runtime.\n', 'Finished report.']);
  const activities = timeline.filter(block => block.type === 'tool').map(block => block.activity);
  assert.deepEqual(activities.map(activity => activity.status), ['completed', 'cancelled', 'failed']);
  assert.equal(activities[0].output, 'Actual source.');
  assert.equal(activities[0].duration_ms, 120);
  assert.equal(activities[0].truncated, true);
  assert.match(activities[2].status_detail, /before a tool result/);
  assert.deepEqual(messageTimeline(saved), timeline);
});

test('saved child tools preserve actor ownership and jump IDs without leaking tagged reasoning or speech', () => {
  const displayed = messageTimeline({ role: 'agent', content: 'Final answer. [[speak]]Spoken answer.[[/speak]]', tools_used: [
    { call_id: 'parent', name: 'spawn_subagent', display_prose_before: '<think>Private thoughts.</think>Delegating inspection. [[speak]]Spoken progress.[[/speak]]', output: 'Worker report.', status: 'completed' },
    { call_id: 'subagent:worker-a:read', name: 'read_file', source_agent: 'worker-a', agent_role: 'tester', output: 'Read evidence.', status: 'completed' },
    { call_id: 'worker-b:read', name: 'read_file', source_actor: { agent_id: 'worker-b', role: 'reviewer' }, status: 'running' },
  ] });
  const activities = displayed.filter(block => block.type === 'tool').map(block => block.activity);
  assert.deepEqual(activities.map(activity => activity.id), ['parent', 'worker-a:read', 'worker-b:read']);
  assert.deepEqual(activities.slice(1).map(activity => activity.source_agent.role), ['tester', 'reviewer']);
  assert.equal(activities[2].status, 'unknown', 'restored records must not pretend a task is still running');
  assert.equal(JSON.stringify(displayed).includes('Private thoughts'), false);
  assert.equal(JSON.stringify(displayed).includes('Spoken'), false);
  assert.deepEqual(text(displayed).map(content => content.trim()), ['Delegating inspection.', 'Final answer.']);
});

test('legacy tools_used remains tools then final and interrupted tool-only turns retain evidence', () => {
  const tools_used = [{ call_id: 'old', name: 'read_file', arguments: { path: 'old' } }];
  assert.deepEqual(types(savedMessageTimeline({ agent: 'Old reply.', tools_used })), ['tool', 'text']);
  const interrupted = savedMessageTimeline({ agent: '', tools_used: [{ ...tools_used[0], status: 'cancelled' }] });
  assert.deepEqual(types(interrupted), ['tool']);
  assert.equal(interrupted[0].activity.status, 'cancelled');
  assert.equal(interrupted[0].activity.output, undefined);
  assert.deepEqual(savedMessageTimeline({ content: '', tools_used: [null, 'invalid'] }), []);
});

test('timeline operations leave previous blocks and nested arguments immutable', () => {
  const input = Object.freeze([Object.freeze({ id: 'text-0', type: 'text', content: 'Read.' })]);
  const event = Object.freeze({ type: 'tool_call', call_id: 'a', name: 'read_file', args: Object.freeze({ path: 'a' }) });
  const started = timelineToolStart(input, event);
  const frozen = Object.freeze(started.map(block => Object.freeze(block)));
  const completed = resolveTimelineTool(frozen, Object.freeze(result('a')));
  assert.equal(input[0].content, 'Read.');
  assert.equal(started[1].activity.status, 'running');
  assert.equal(completed[1].activity.status, 'completed');
});

test('subagent tool owner metadata survives in-place completion and terminal state', () => {
  let timeline = timelineToolStart([], { type: 'tool_call', tool_call: {
    id: 'worker:a', name: 'read_file', agent_role: 'tester', source_agent: 'worker',
  } });
  timeline = appendTimelineText(timeline, 'The parent continues.');
  const id = timeline[0].id;
  timeline = resolveTimelineTool(timeline, { type: 'tool_result', tool_result: { call_id: 'worker:a', content: 'Test report.' } });
  assert.equal(timeline[0].id, id);
  assert.equal(timeline[0].activity.agent_role, 'tester');
  assert.equal(timeline[0].activity.source_agent, 'worker');
  assert.equal(timeline[0].activity.status, 'completed');
  assert.equal(finishTimelineTools(timeline, 'completed')[0].activity.source_agent, 'worker');
});

test('one actor finishing leaves sibling and parent running cards untouched', () => {
  let timeline = timelineToolStart([], start('parent'));
  for (const actor of ['worker-a', 'worker-b']) timeline = timelineToolStart(timeline, {
    ...start(`${actor}:read`), source_agent: { agent_id: actor, role: 'tester' },
  });
  const finished = finishActorTimelineTools(timeline, 'worker-a', 'failed');
  assert.deepEqual(finished.map(block => block.activity.status), ['running', 'failed', 'running']);
  assert.deepEqual(finished.map(block => block.id), timeline.map(block => block.id));
  assert.equal(finished[1].activity.source_agent.role, 'tester');
});
