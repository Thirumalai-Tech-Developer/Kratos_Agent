export function liveStatusView(status, pending, controlError = '') {
  const runtime = status?.runtime_started === true;
  const speech = status?.speech_started === true;
  const enabled = status?.speech_enabled !== false;
  const backend = status?.speech_backend || 'gemini';
  const errors = status?.errors || {};
  const speechError = status?.start_error || errors.live_speech || errors.gemini_speech || errors.gemini || '';
  const starting = pending && ['reconnect', 'start', 'unmute', 'toggle_mute'].includes(pending.action) && (!runtime || !speech || pending.action === 'reconnect');
  const nativeReady = status?.speech_healthy === true || status?.speech_healthy !== false && status?.live_health === 'native';
  const online = runtime && speech && enabled && (backend === 'native' ? nativeReady : status?.gemini_connected === true);
  const state = starting ? 'STARTING' : online ? 'ONLINE' : runtime && speech && enabled && !speechError ? 'CONNECTING' : 'OFFLINE';
  const muted = status?.muted === true;
  const microphoneActive = runtime && status?.microphone_active === true && !muted;
  const camera = runtime && status?.camera_active === true;
  const screen = runtime && status?.screen_active === true;
  return {
    state, online, runtime, speech, backend, microphoneActive, muted,
    speakerActive: runtime && status?.speaker_active === true,
    visionMode: camera && screen ? 'both' : camera ? 'camera' : screen ? 'screen' : 'none',
    microphoneLabel: muted ? 'Muted' : microphoneActive ? 'Mic on' : 'Mic off',
    microphoneAction: microphoneActive && !muted ? 'mute' : 'unmute',
    error: controlError || speechError || errors.microphone || errors.speech_recognition || errors.speaker || '',
    microphoneError: errors.microphone || errors.speech_recognition || '',
  };
}
