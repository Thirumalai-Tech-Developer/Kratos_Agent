// Keep incomplete code fences separate from prose while the reply streams.
// Mermaid is rendered only after the closing fence arrives.
export function markdownSegments(value) {
  const lines = String(value ?? '').match(/[^\n]*\n|[^\n]+$/g) || [];
  const segments = [];
  let prose = '';

  for (let index = 0; index < lines.length; index += 1) {
    const opening = lines[index].match(/^ {0,3}(`{3,}|~{3,})([^\r\n]*)\r?\n?$/);
    if (!opening || (opening[1][0] === '`' && opening[2].includes('`'))) {
      prose += lines[index];
      continue;
    }
    if (prose) {
      segments.push({ type: 'text', content: prose });
      prose = '';
    }
    const marker = opening[1][0];
    const close = new RegExp(`^ {0,3}${marker}{${opening[1].length},}[\\t ]*\\r?\\n?$`);
    let code = '';
    let complete = false;
    while (++index < lines.length) {
      if (close.test(lines[index])) {
        complete = true;
        break;
      }
      code += lines[index];
    }
    segments.push({
      type: 'code', lang: opening[2].trim().split(/\s+/)[0].toLowerCase(), code, complete,
    });
  }
  if (prose) segments.push({ type: 'text', content: prose });
  return segments;
}
