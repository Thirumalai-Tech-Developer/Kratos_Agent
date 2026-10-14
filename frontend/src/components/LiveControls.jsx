import React from 'react';
import { Mic, MicOff, Volume2, VolumeX, RotateCw, Radio, LoaderCircle } from 'lucide-react';
import { liveStatusView } from '../liveStatusView';

export default function LiveControls({ status, error, pending, onControl }) {
  const view = liveStatusView(status, pending, error);
  const microphonePending = ['mute', 'unmute', 'toggle_mute'].includes(pending?.action);
  const reconnectPending = pending?.action === 'reconnect';
  return <div className="live-controls" aria-label="Voice controls">
    <span className={`live-connection ${view.online ? 'is-connected' : ''}`} title={`${view.backend === 'native' ? 'Local' : 'Gemini'} speech output${status?.speech_model ? ` · ${status.speech_model}` : ''}`} role="status">
      {view.state === 'STARTING' || view.state === 'CONNECTING' ? <LoaderCircle size={13} className="animate-spin" /> : <Radio size={13} />}Voice {view.state}</span>
    <button type="button" onClick={() => onControl?.(view.microphoneAction)} disabled={Boolean(pending)}
      aria-label={microphonePending ? 'Updating microphone' : view.microphoneAction === 'mute' ? 'Mute microphone' : view.speech ? 'Unmute microphone' : 'Start microphone'}
      aria-pressed={view.muted} title={view.microphoneError || (view.muted ? 'Microphone muted' : 'Microphone control')}>
      {microphonePending ? <LoaderCircle size={15} className="animate-spin" /> : view.microphoneActive ? <Mic size={15} /> : <MicOff size={15} />}<span>{microphonePending ? 'Updating…' : view.microphoneLabel}</span>
    </button>
    <span className="live-output" title={status?.errors?.speaker || 'Speech playback'}>{view.speakerActive ? <Volume2 size={14} /> : <VolumeX size={14} />}<span>{view.speakerActive ? 'Audio on' : 'Audio off'}</span></span>
    <button type="button" className="live-reconnect" onClick={() => onControl?.('reconnect')} disabled={Boolean(pending)} aria-label={reconnectPending ? 'Starting voice session' : view.speech ? 'Reconnect voice session' : 'Start voice session'} title="Start or reconnect this workspace’s speech output">
      {reconnectPending ? <LoaderCircle size={14} className="animate-spin" /> : <RotateCw size={14} />}{!view.speech && <span>Start voice</span>}</button>
    {view.error && <span className="live-control-error" role="status">{view.error}</span>}
  </div>;
}
