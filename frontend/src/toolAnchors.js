export function toolCardAnchor(messageIndex, callId) {
  return `tool-${messageIndex}-${encodeURIComponent(String(callId))}`;
}
