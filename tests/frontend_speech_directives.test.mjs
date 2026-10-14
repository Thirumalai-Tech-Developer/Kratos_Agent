import assert from 'node:assert/strict';
import test from 'node:test';
import { visibleAssistantText, visibleMessageText } from '../frontend/src/speechDirectives.js';

test('restored assistant answer renders once while speech summary stays hidden', () => {
  const reply = "Hey! I'm here and ready to help. What would you like to work on? [[speak]]Hi! I'm ready — tell me what you'd like to work on.[[/speak]]";
  assert.equal(visibleMessageText({ role: 'assistant', content: reply }), "Hey! I'm here and ready to help. What would you like to work on?");
  assert.equal(visibleMessageText({ role: 'agent', content: reply }), "Hey! I'm here and ready to help. What would you like to work on?");
});

test('every streamed prefix keeps markers and speech body out of the answer', () => {
  const visible = 'The report is ready. ';
  const reply = visible + '[[speak]]The report is ready.[[/speak]]';
  for (let boundary = visible.length; boundary <= reply.length; boundary += 1) {
    assert.equal(visibleAssistantText(reply.slice(0, boundary)), visible.trim());
  }
});

test('visible text after speech metadata is retained and malformed metadata is hidden', () => {
  assert.equal(visibleAssistantText('Before [[speak]]audio only[[/speak]] after'), 'Before  after');
  assert.equal(visibleAssistantText('Answer. [[speak]]unfinished phrase'), 'Answer.');
  assert.equal(visibleAssistantText('Answer. [[speak]]outer [[speak]]inner[[/speak]][[/speak]]'), 'Answer.');
});

test('user text preserves literal speech marker examples', () => {
  const content = 'How do I use [[speak]]hello[[/speak]]?';
  assert.equal(visibleMessageText({ role: 'user', content }), content);
});
