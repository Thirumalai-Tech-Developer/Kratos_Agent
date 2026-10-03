/** Keep tool events separate from model prose, including older SSE payloads. */
export function isToolEvent(data) {
  return ['tool_call', 'tool_result', 'tool_failed'].includes(data.type) || Boolean(data.tool_call || data.tool_result);
}

export function updateToolActivity(previous = [], data) {
  const call = typeof data.tool_call === 'object' ? data.tool_call : {};
  const result = typeof data.tool_result === 'object' ? data.tool_result : {};
  const name = call.name || result.name || data.name || (typeof data.tool_call === 'string' ? data.tool_call : 'tool');
  const callId = call.call_id || result.call_id || data.call_id || call.id || result.id;
  const starting = data.type === 'tool_call' || Boolean(data.tool_call);
  let index = callId ? previous.findIndex(item => item.id === callId) : -1;
  if (index < 0 && !starting) index = previous.findIndex(item => item.name === name && item.status === 'running');
  const item = index >= 0 ? previous[index] : { id: callId || `tool-${previous.length}`, name };
  const updated = {
    ...item,
    name,
    label: call.label || item.label || name,
    arguments: call.args ?? call.arguments ?? data.args ?? item.arguments,
    status: starting ? 'running' : (data.status === 'cancelled' ? 'cancelled' : (data.is_error || result.is_error || data.type === 'tool_failed' || data.status === 'failed' ? 'failed' : 'completed')),
    ...(starting ? {} : { output: result.content ?? result.result ?? data.result ?? data.content ?? data.tool_result, truncated: Boolean(result.truncated || data.truncated) }),
  };
  if (index < 0) return [...previous, updated];
  return previous.map((entry, i) => i === index ? updated : entry);
}

export function finishToolActivity(previous = [], status) {
  return previous.map(item => item.status === 'running' ? {
    ...item, status: status === 'cancelled' ? 'cancelled' : (status === 'failed' ? 'failed' : 'unknown'),
  } : item);
}

export function restoredToolActivity(calls = []) {
  return calls.map((call, index) => ({
    id: call.call_id || `saved-tool-${index}`, name: call.name || 'tool', label: call.action_label || call.name || 'tool',
    arguments: call.arguments || call.args,
    // Older sessions saved invocations without their result. Do not invent success.
    status: call.is_error ? 'failed' : (call.result !== undefined || call.content !== undefined ? 'completed' : 'unknown'),
    output: call.result ?? call.content,
  }));
}
