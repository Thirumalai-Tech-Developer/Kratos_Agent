import { test } from 'node:test';
import assert from 'node:assert/strict';
import { profileRequestPath, getUserProfile } from '../src/userProfile.js';

test('integrated and standalone requests retain profile isolation', () => {
  assert.equal(profileRequestPath('/api/chat', 'a'.repeat(32), true), `/api/kratos/chat?profile=${'a'.repeat(32)}`);
  assert.equal(profileRequestPath('/api/models?refresh=1', 'b'.repeat(32), false), `/api/models?refresh=1&profile=${'b'.repeat(32)}`);
});

test('non-API paths are not tagged with a user profile', () => {
  assert.equal(profileRequestPath('/kratos_badge.png', 'a'.repeat(32), false), '/kratos_badge.png');
});

test('one browser keeps a stable validated profile across requests', () => {
  globalThis.localStorage = { getItem: () => 'a'.repeat(32), setItem: () => {} };
  assert.equal(getUserProfile(), 'a'.repeat(32));
  assert.equal(getUserProfile(), getUserProfile());
});

test('storage restrictions still keep an isolated profile for the open page', async () => {
  globalThis.localStorage = { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); } };
  const fresh = await import('../src/userProfile.js?blocked-storage');
  assert.match(fresh.getUserProfile(), /^[a-f0-9]{32}$/);
  assert.equal(fresh.getUserProfile(), fresh.getUserProfile());
});
