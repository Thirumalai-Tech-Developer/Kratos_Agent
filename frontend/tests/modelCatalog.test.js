import assert from 'node:assert/strict';
import { test } from 'node:test';
import { groupModelCatalog, modelModalityLabel, normalizeModelCatalog } from '../src/modelCatalog.js';

test('Provider identifiers stay intact across duplicates, friendly names, and invalid catalog entries', () => {
  const opaqueId = 'qwen-web/Qwen2.8-Max?variant=thinking';
  const catalog = normalizeModelCatalog([null, {}, { id: ' ' }, { id: opaqueId, name: 'Qwen 2.8 Max', provider: 'Qwen' },
    { id: opaqueId, name: 'Duplicate' }, { id: 'dola-web/dola', provider_name: 'Dola', name: '' }]);
  assert.equal(catalog.length, 2);
  assert.equal(catalog[0].id, opaqueId);
  assert.equal(catalog[0].name, 'Qwen 2.8 Max');
  assert.equal(catalog[1].provider, 'Dola');
  assert.equal(catalog[1].name, 'dola-web/dola');
});

test('A multi-word search finds a model using both its provider and version without changing IDs', () => {
  const catalog = normalizeModelCatalog([{ id: 'qwen/omni-flash', name: 'Qwen 2.8 OmniFlash', provider: 'Qwen' },
    { id: 'qwen/max', name: 'Qwen 2.8 Max', provider: 'Qwen' }, { id: 'dola/dola', name: 'Dola', provider: 'Dola' }]);
  const groups = groupModelCatalog(catalog, 'QWEN 2.8 flash');
  assert.deepEqual(groups.map(group => group.models.map(model => model.id)), [['qwen/omni-flash']]);
  assert.deepEqual(groupModelCatalog(catalog).map(group => group.provider), ['Dola', 'Qwen']);
});

test('Explicit account restrictions disable entries, but missing optional availability is selectable', () => {
  const catalog = normalizeModelCatalog([{ id: 'qwen/max' }, { id: 'claude/paid', available: false, disabled_reason: 'Requires a paid plan' },
    { id: 'meta/restricted', isAvailable: false }, { id: 'kimi/disabled', disabled: true }]);
  assert.deepEqual(catalog.map(model => model.disabled), [false, true, true, true]);
  assert.equal(catalog[1].disabledReason, 'Requires a paid plan');
  assert.throws(() => normalizeModelCatalog({ models: [] }), /catalog could not be read/);
});

test('Vision is shown only when provider metadata reports it, with unknown capabilities preserved', () => {
  assert.equal(modelModalityLabel({ supports_text_input: true, supports_image_input: true }), '📝 Text + 👁️ Vision');
  assert.equal(modelModalityLabel({ input_modalities: ['text'] }), '📝 Text');
  assert.equal(modelModalityLabel({ input_modalities: ['image'] }), '👁️ Vision');
  assert.equal(modelModalityLabel({ supports_text_input: true, supports_image_input: null }), '📝 Text · vision not reported');
  assert.equal(modelModalityLabel({ input_modalities: ['text'], supports_image_input: null, modality_label: 'Text' }), '📝 Text · vision not reported');
  assert.equal(modelModalityLabel({ name: 'Ultra Vision Max' }), 'Capabilities not reported');
  assert.equal(modelModalityLabel({ modality_label: '📝 Text + 👁️ Vision + 🔊 Audio' }), '📝 Text + 👁️ Vision + 🔊 Audio');
});
