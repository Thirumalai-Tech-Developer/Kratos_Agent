import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const source = await readFile(new URL('../src/kratos_agent/brain/chatgpt_browser_extension/content.js', import.meta.url), 'utf8');

test('an extension reload retires stale website polling without uncaught errors', () => {
  let tick;
  let cleared;
  let messages = 0;
  let invalidated = false;
  const context = {chrome:{runtime:{id:'current-extension',onMessage:{addListener(){}},sendMessage() {
    if (invalidated) throw new Error('Extension context invalidated.');
    messages++;
    return Promise.resolve();
  }}},setInterval(fn) {tick=fn;return 7;},clearInterval(id) {cleared=id;}};
  vm.runInNewContext(source, context);
  assert.equal(messages, 1);
  tick();
  assert.equal(messages, 2);
  invalidated = true;
  assert.doesNotThrow(tick);
  assert.equal(cleared, 7);
  assert.equal(messages, 2);
});

test('an already invalidated website script starts no timer or browser work', () => {
  let timers = 0;
  let messages = 0;
  vm.runInNewContext(source, {chrome:{runtime:{sendMessage() {messages++;}}},setInterval() {timers++;},clearInterval() {}});
  assert.equal(timers, 0);
  assert.equal(messages, 0);
});
