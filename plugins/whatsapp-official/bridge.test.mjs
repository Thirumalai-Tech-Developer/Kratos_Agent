import { test } from 'node:test';
import assert from 'node:assert/strict';
import { processMessage, validateConfig } from './bridge.mjs';

const config = () => validateConfig({ ROUTING_BASE_URL: 'http://127.0.0.1:28080', ROUTING_API_KEY: 'test-key',
  WHATSAPP_ALLOWED_PHONES: '971501234567', KRATOS_INTERNAL_TOKEN: 'private-test-token' });
const message = () => ({ type: 'INBOUND_MESSAGE', message_id: 'message-1', payload: { from: '971501234567', text: 'hello' } });

test('requires credentials, allowed sender, and secure remote routing', () => {
  assert.throws(() => validateConfig({}), /Missing configuration/);
  assert.equal(config().agentMode, false);
  assert.throws(() => validateConfig({ ROUTING_BASE_URL: 'http://remote.example', ROUTING_API_KEY: 'key',
    WHATSAPP_ALLOWED_PHONES: '971501234567', KRATOS_INTERNAL_TOKEN: 'token' }), /requires HTTPS/);
});

test('persists a sender session, resumes it, and skips duplicate events', async () => {
  const state = { sessions: {}, seen: [] };
  const calls = [], sent = [];
  const deps = { save: async () => {}, agent: async (path, body) => {
    calls.push({ path, body });
    return path === '/api/sessions' ? { session_id: 'kratos-session' } : { status: 'success', reply: 'Kratos reply' };
  }, send: async (phone, text) => { sent.push({ phone, text }); } };
  assert.equal(await processMessage(message(), config(), state, deps), true);
  assert.equal(calls[1].body.session_id, 'kratos-session');
  assert.equal(calls[1].body.agent_mode, false);
  assert.equal(sent[0].text, 'Kratos reply');
  assert.equal(await processMessage(message(), config(), state, deps), false);
  assert.equal(calls.length, 2);
  const next = message(); next.message_id = 'message-2';
  await processMessage(next, config(), state, deps);
  assert.equal(calls.length, 3);
});

test('unknown sender and unsupported attachment never reach the agent', async () => {
  const state = { sessions: {}, seen: [] };
  const deps = { agent: () => { throw new Error('Agent must not run'); } };
  const unknown = message(); unknown.payload.from = '15551234567';
  assert.equal(await processMessage(unknown, config(), state, deps), false);
  const attachment = message(); delete attachment.payload.text; attachment.payload.mediaId = 'photo';
  assert.equal(await processMessage(attachment, config(), state, deps), false);
});

test('failed agent turn is not sent as a successful reply or automatically retried', async () => {
  const state = { sessions: { '971501234567': 'existing' }, seen: [] };
  let runs = 0;
  const deps = { save: async () => {}, agent: async () => { runs++; return { status: 'failed', result: 'failure' }; },
    send: async () => { throw new Error('Must not send failure as reply'); } };
  await assert.rejects(processMessage(message(), config(), state, deps), /could not complete/);
  assert.equal(await processMessage(message(), config(), state, deps), false);
  assert.equal(runs, 1);
});
