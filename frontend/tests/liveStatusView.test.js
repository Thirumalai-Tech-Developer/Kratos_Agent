import assert from 'node:assert/strict';
import test from 'node:test';
import { liveStatusView } from '../src/liveStatusView.js';

test('a stopped profile does not inherit another runtime connection or configured camera mode', () => {
  const view = liveStatusView({ runtime_started: false, speech_started: false, gemini_connected: true, video_mode: 'camera', camera_active: true });
  assert.equal(view.state, 'OFFLINE');
  assert.equal(view.online, false);
  assert.equal(view.visionMode, 'none');
});
test('voice start, connecting, confirmed connection and disabled speech remain distinct', () => {
  const status = { runtime_started: true, speech_started: true, speech_enabled: true, speech_backend: 'gemini', gemini_connected: false };
  assert.equal(liveStatusView(null, { action: 'reconnect' }).state, 'STARTING');
  assert.equal(liveStatusView(status).state, 'CONNECTING');
  assert.equal(liveStatusView({ ...status, gemini_connected: true }).state, 'ONLINE');
  assert.equal(liveStatusView({ ...status, speech_enabled: false }).state, 'OFFLINE');
  assert.equal(liveStatusView({ ...status, start_error: 'API key missing' }).state, 'OFFLINE');
});
test('vision loop without speech shows actual capture and leaves speech offline', () => {
  const view = liveStatusView({ runtime_started: true, speech_started: false, camera_active: true, screen_active: true, video_mode: 'both' });
  assert.equal(view.state, 'OFFLINE');
  assert.equal(view.visionMode, 'both');
  assert.equal(liveStatusView({ runtime_started: true, video_mode: 'screen', screen_active: false }).visionMode, 'none');
});
test('Windows microphone failure is visible without claiming Gemini failed or the mic is active', () => {
  const view = liveStatusView({ runtime_started: true, speech_started: true, speech_enabled: true, speech_backend: 'gemini', gemini_connected: true,
    microphone_active: false, muted: false, errors: { microphone: 'Allow microphone access in Windows Settings.' } });
  assert.equal(view.state, 'ONLINE');
  assert.equal(view.microphoneLabel, 'Mic off');
  assert.equal(view.microphoneAction, 'unmute');
  assert.match(view.error, /Windows Settings/);
});

test('native speech uses its reported ready lifecycle and respects explicitly unhealthy state', () => {
  const status = { runtime_started: true, speech_started: true, speech_enabled: true, speech_backend: 'native', live_health: 'native' };
  assert.equal(liveStatusView(status).state, 'ONLINE');
  assert.equal(liveStatusView({ ...status, runtime_started: false }).state, 'OFFLINE');
  assert.equal(liveStatusView({ ...status, speech_started: false }).state, 'OFFLINE');
  assert.equal(liveStatusView({ ...status, speech_healthy: false }).online, false);
  assert.equal(liveStatusView({ ...status, live_health: 'offline' }).online, false);
});

test('speech recognition errors remain actionable without marking connected speech output offline', () => {
  const view = liveStatusView({ runtime_started: true, speech_started: true, speech_enabled: true, speech_backend: 'gemini', gemini_connected: true,
    microphone_active: false, errors: { speech_recognition: 'Local speech recognition stopped. Click Unmute to retry.' } });
  assert.equal(view.state, 'ONLINE');
  assert.equal(view.microphoneActive, false);
  assert.equal(view.microphoneAction, 'unmute');
  assert.match(view.error, /Unmute to retry/);
  assert.equal(view.microphoneError, view.error);
});
