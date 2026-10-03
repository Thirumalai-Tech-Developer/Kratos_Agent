import assert from 'node:assert/strict';
import { test } from 'node:test';
import { isToolEvent, updateToolActivity, finishToolActivity } from '../src/chatActivity.js';

test('Tool output is classified as activity even when it carries a top-level result', () => {
  assert.equal(isToolEvent({ type: 'tool_result', result: 'large terminal output' }), true);
  assert.equal(isToolEvent({ type: 'done', result: 'Final model reply' }), false);
});

test('Repeated and concurrent tools are paired using call IDs, preserving failure and output', () => {
  let activities = updateToolActivity([], { type: 'tool_call', tool_call: { call_id: 'a', name: 'read_file', args: { file_path: 'a.py' } } });
  activities = updateToolActivity(activities, { type: 'tool_call', tool_call: { call_id: 'b', name: 'read_file', args: { file_path: 'b.py' } } });
  activities = updateToolActivity(activities, { type: 'tool_failed', call_id: 'b', name: 'read_file', is_error: true, result: 'Missing file' });
  assert.equal(activities[0].status, 'running');
  assert.equal(activities[1].status, 'failed');
  assert.equal(activities[1].output, 'Missing file');
  assert.equal(activities.length, 2);
});

test('Stop acknowledges cancelled tools and does not invent success for unfinished activity', () => {
  const activities = updateToolActivity([], { type: 'tool_failed', call_id: 'a', name: 'terminal', is_error: true, status: 'cancelled', result: 'Cancelled by user' });
  assert.equal(activities[0].status, 'cancelled');
  const running = updateToolActivity([], { type: 'tool_call', name: 'terminal', call_id: 'a' });
  assert.equal(finishToolActivity(running, 'cancelled')[0].status, 'cancelled');
  assert.equal(finishToolActivity(running, 'completed')[0].status, 'unknown');
});
