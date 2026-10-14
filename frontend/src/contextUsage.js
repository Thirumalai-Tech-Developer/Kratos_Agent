export function formatContextTokens(value) {
  if (!Number.isFinite(value) || value < 0) return '—';
  if (value < 1000) return Math.round(value).toLocaleString();
  const divisor = value >= 1000000 ? 1000000 : 1000;
  return `${(value / divisor).toLocaleString(undefined, { maximumFractionDigits: 1 })}${divisor === 1000000 ? 'M' : 'k'}`;
}

export function contextUsageView(context) {
  if (!context || !Number.isFinite(context.used_tokens) || !Number.isFinite(context.input_limit) || context.input_limit <= 0) return null;
  const used = Math.max(0, context.used_tokens);
  const percent = Math.round(used / context.input_limit * 1000) / 10;
  return {
    used, percent, progress: Math.min(100, percent),
    remaining: Math.max(0, context.input_limit - used),
    tone: percent >= 100 ? 'danger' : percent >= 80 ? 'warning' : 'normal',
    estimated: context.measurement !== 'provider',
    lastSaved: Math.max(0, context.last_compaction?.saved_tokens || 0),
  };
}
