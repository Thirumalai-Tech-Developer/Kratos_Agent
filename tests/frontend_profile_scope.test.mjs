import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { createUserProfileResolver, getUserProfile, profileRequestPath, USER_PROFILE_STORAGE_KEY } from '../services/omniroute/src/lib/kratos/browserWorkspaceProfile.js';
import * as frontend from '../frontend/src/userProfile.js';

function browser(saved, search = '') {
  const values = new Map(saved ? [[USER_PROFILE_STORAGE_KEY, saved]] : []);
  return { location: { search }, crypto: { getRandomValues: array => array.fill(5) }, localStorage: {
    getItem: key => values.get(key), setItem: (key, value) => values.set(key, value),
  } };
}

test('chat and management use the same helper and persisted profile', () => {
  assert.equal(frontend.getUserProfile, getUserProfile);
  assert.equal(frontend.profileRequestPath, profileRequestPath);
  const storage = browser('a'.repeat(32));
  const chat = createUserProfileResolver(() => storage);
  const settings = createUserProfileResolver(() => storage);
  assert.equal(chat(), settings());
  assert.equal(profileRequestPath('/api/chat', chat(), true), '/api/kratos/chat?profile=' + 'a'.repeat(32));
  assert.equal(profileRequestPath('/api/mcp', settings(), true), '/api/kratos/mcp?profile=' + 'a'.repeat(32));
});

test('a settings link can carry its exact chat profile and persist it for returning to chat', () => {
  const storage = browser('a'.repeat(32), '?profile=' + 'b'.repeat(32));
  const settings = createUserProfileResolver(() => storage);
  assert.equal(settings(), 'b'.repeat(32));
  storage.location.search = '';
  assert.equal(createUserProfileResolver(() => storage)(), 'b'.repeat(32));
});

test('malformed URL or saved profiles never silently target the owner workspace', () => {
  const storage = browser('../invalid', '?profile=invalid');
  const resolve = createUserProfileResolver(() => storage);
  assert.match(resolve(), /^[a-f0-9]{32}$/);
  assert.equal(resolve(), resolve());
  assert.throws(() => profileRequestPath('/api/mcp', 'invalid', true));
});

test('blocked browser storage keeps an in-memory profile and accepts explicit scoped links', () => {
  const storage = browser(null);
  storage.localStorage = { getItem() { throw Error('Blocked'); }, setItem() { throw Error('Blocked'); } };
  const resolve = createUserProfileResolver(() => storage);
  assert.equal(resolve(), '05'.repeat(16));
  assert.equal(resolve(), '05'.repeat(16));
  storage.location.search = '?profile=' + 'c'.repeat(32);
  assert.equal(resolve(), 'c'.repeat(32));
});

test('scope replacement retains other query options and fragments without duplicate profiles', () => {
  assert.equal(profileRequestPath('/api/mcp?refresh=1&profile=old#details', 'a'.repeat(32), true), '/api/kratos/mcp?refresh=1&profile=' + 'a'.repeat(32) + '#details');
  assert.equal(profileRequestPath('/api/kratos/mcp', 'a'.repeat(32), true), '/api/kratos/mcp?profile=' + 'a'.repeat(32));
  assert.equal(profileRequestPath('/api/tools', 'a'.repeat(32), false), '/api/tools?profile=' + 'a'.repeat(32));
  assert.equal(profileRequestPath('/assets/logo.svg', 'a'.repeat(32), true), '/assets/logo.svg');
});

test('management GET and mutations are both explicitly scoped to the selected workspace', () => {
  const page = readFileSync(new URL('../services/omniroute/src/app/(dashboard)/dashboard/kratos/mcp/page.tsx', import.meta.url), 'utf8');
  assert.ok(page.includes('profileRequestPath("/api/mcp", selectedProfile, true)'));
  assert.ok(page.includes('profileRequestPath("/api/mcp", profile || getUserProfile(), true)'));
  assert.equal(page.includes('fetch("/api/kratos/mcp"'), false);
});

test('embedded workspace resolves identity after mount and preserves scope in navigation and controls', () => {
  const page = readFileSync(new URL('../services/omniroute/src/app/(dashboard)/dashboard/kratos/page.tsx', import.meta.url), 'utf8');
  assert.ok(page.includes('useEffect(() => { setProfile(getUserProfile()); }, [])'));
  assert.ok(page.includes('if (!profile) return;'));
  assert.ok(page.includes('profileRequestPath("/api/health", profile, true)'));
  assert.ok(page.includes('profileRequestPath("/api/chat/cancel", profile, true)'));
  assert.ok(page.includes('/dashboard/kratos/mcp?profile=${profile}'));
  assert.ok(page.includes('/dashboard/kratos/workspace/index.html?profile=${profile}'));
  assert.ok(page.includes('{profile && status !== "offline" && <iframe'));
});
