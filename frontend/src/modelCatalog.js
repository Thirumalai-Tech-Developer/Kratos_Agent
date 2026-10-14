/** Keep provider model identifiers intact when organizing the picker. */
export function normalizeModelCatalog(entries) {
  if (!Array.isArray(entries)) throw new Error('The model catalog could not be read. Try refreshing it.');
  const seen = new Set();
  return entries.filter(entry => {
    const key = entry?.selection_key || entry?.id;
    if (!entry || typeof entry.id !== 'string' || !entry.id.trim() || seen.has(key)) return false;
    seen.add(key);
    return true;
  }).map(entry => ({
    ...entry,
    name: typeof entry.name === 'string' && entry.name.trim() ? entry.name : entry.display_name || entry.id,
    provider: typeof entry.provider_name === 'string' && entry.provider_name.trim()
      ? entry.provider_name
      : typeof entry.provider === 'string' && entry.provider.trim()
        ? entry.provider
        : entry.id.includes('/') ? entry.id.split('/')[0] : 'Other providers',
    disabled: entry.disabled === true || entry.available === false || entry.isAvailable === false,
    disabledReason: typeof entry.disabledReason === 'string' ? entry.disabledReason : typeof entry.disabled_reason === 'string' ? entry.disabled_reason : '',
  }));
}

export function modelModalityLabel(model) {
  if (typeof model?.modality_label === 'string' && (model.modality_label.includes('📝') || model.modality_label.includes('👁'))) return model.modality_label;
  const modalities = Array.isArray(model?.input_modalities) && model.input_modalities.length ? model.input_modalities : null;
  const text = typeof model?.supports_text_input === 'boolean' || model?.supports_text_input === null ? model.supports_text_input : modalities ? modalities.includes('text') : null;
  const vision = typeof model?.supports_image_input === 'boolean' || model?.supports_image_input === null ? model.supports_image_input : modalities ? modalities.includes('image') : null;
  if (text === true && vision === true) return '📝 Text + 👁️ Vision';
  if (text === true && vision === false) return '📝 Text';
  if (text === false && vision === true) return '👁️ Vision';
  if (text === true) return '📝 Text · vision not reported';
  if (vision === true) return '👁️ Vision · text not reported';
  return 'Capabilities not reported';
}

export function groupModelCatalog(models, query = '') {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const groups = new Map();
  for (const model of models) {
    const searchable = `${model.name} ${model.id} ${model.provider}`.toLowerCase();
    if (!terms.every(term => searchable.includes(term))) continue;
    if (!groups.has(model.provider)) groups.set(model.provider, []);
    groups.get(model.provider).push(model);
  }
  return [...groups.entries()].sort(([left], [right]) => left.localeCompare(right))
    .map(([provider, entries]) => ({ provider, models: entries.sort((left, right) => left.name.localeCompare(right.name)) }));
}

/** Update the confirmed connection locally without fetching its catalog again. */
export function withSelectedCatalogModel(models, modelId, connection) {
  return models.map(model => ({
    ...model,
    is_configured: model.id === modelId && (typeof connection !== 'string' || model.selection_key === connection),
  }));
}
