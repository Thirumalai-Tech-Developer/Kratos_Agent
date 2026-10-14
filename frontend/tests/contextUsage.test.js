import { test } from 'node:test';
import assert from 'node:assert/strict';
import { contextUsageView, formatContextTokens } from '../src/contextUsage.js';

test('context uses the input budget after reserving output', () => {
  const view = contextUsageView({ used_tokens: 124000, input_limit: 248000, context_limit: 256000, measurement: 'estimated' });
  assert.equal(view.percent, 50);
  assert.equal(view.remaining, 124000);
  assert.equal(view.estimated, true);
});

test('over-limit input is visible and the progress bar is bounded', () => {
  const view = contextUsageView({ used_tokens: 300000, input_limit: 248000 });
  assert.equal(view.progress, 100);
  assert.ok(view.percent > 100);
  assert.equal(view.remaining, 0);
  assert.equal(view.tone, 'danger');
});

test('provider counts, zero usage, and saved tokens stay distinct', () => {
  const view = contextUsageView({ used_tokens: 0, input_limit: 248000, measurement: 'provider', last_compaction: { saved_tokens: 8200 } });
  assert.equal(view.estimated, false);
  assert.equal(view.percent, 0);
  assert.equal(view.lastSaved, 8200);
});

test('unavailable limits do not become a fake context capacity', () => {
  for (const value of [null, {}, { used_tokens: 1, input_limit: 0 }, { used_tokens: 1, input_limit: NaN }]) {
    assert.equal(contextUsageView(value), null);
  }
});

test('token formatting supports large model windows', () => {
  assert.equal(formatContextTokens(256000), '256k');
  assert.equal(formatContextTokens(1000000), '1M');
  assert.equal(formatContextTokens(null), '—');
});
