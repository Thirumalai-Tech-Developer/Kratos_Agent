/** Recovery events are progress, never a terminal task acknowledgement. */
export function isRecoveryEvent(event) {
  if (event?.recoverable === false) return false;
  return ['retry', 'runtime.retry'].includes(event?.type) || event?.kind === 'runtime.retry';
}

const legacyToolFormatFailure = /^\s*(?:Model request failed:\s*)?The provider still returned invalid tool calls after \d+ correction attempts\.\s*(?:No tool calls from those rejected responses were executed\.)?\s*$/i;

export function isToolFormatFailure(value) {
  return typeof value === 'string' && legacyToolFormatFailure.test(value);
}

/** Keep earlier failed attempts in Activity without repeating them as answers. */
export function isSavedToolFormatFailure(message) {
  return message?.role !== 'user' && message?.status === 'failed' &&
    isToolFormatFailure(message.content);
}

export const RECOVERY_NOTICE_MS = 5000;
