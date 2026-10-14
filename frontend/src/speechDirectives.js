const OPEN = '[[speak]]';
const CLOSE = '[[/speak]]';

// Responses restored from older sessions can contain raw audio metadata. Hide
// it at the display boundary as well as in the backend's streamed output.
export function visibleAssistantText(value, { trim = true } = {}) {
  const source = String(value ?? '');
  let cursor = 0;
  let depth = 0;
  let visible = '';

  while (cursor < source.length) {
    if (source.startsWith(OPEN, cursor)) {
      depth += 1;
      cursor += OPEN.length;
    } else if (source.startsWith(CLOSE, cursor)) {
      depth = Math.max(0, depth - 1);
      cursor += CLOSE.length;
    } else if (source.length - cursor < CLOSE.length &&
      (OPEN.startsWith(source.slice(cursor)) || CLOSE.startsWith(source.slice(cursor)))) {
      // Wait for the rest of a marker during streaming. A truncated marker
      // must not appear as a second answer or expose the control syntax.
      break;
    } else {
      if (!depth) visible += source[cursor];
      cursor += 1;
    }
  }

  return trim ? visible.trim() : visible;
}

export function visibleMessageText(message) {
  return ['assistant', 'agent'].includes(message.role)
    ? visibleAssistantText(message.content)
    : message.content;
}
