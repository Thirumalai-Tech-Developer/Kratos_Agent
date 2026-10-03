import React, { useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';
import { apiFetch } from '../api';

export default function ModelSettings({ onClose, isExecuting }) {
  const dialog = useRef(null);
  const [settings, setSettings] = useState(null);
  const [values, setValues] = useState({});
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    const previous = document.activeElement;
    const element = dialog.current;
    element.showModal();
    let alive = true;
    apiFetch('/api/settings').then(async response => {
      if (!response.ok) throw new Error('Restart Studio to enable model settings.');
      const data = await response.json();
      if (alive) { setSettings(data); setValues({ ...data.options, inspection_limit: data.inspection_limit }); }
    }).catch(failure => { if (alive) setError(failure.message); });
    return () => { alive = false; element.close(); if (previous?.isConnected) previous.focus(); };
  }, []);
  const update = (name, value) => setValues(previous => ({ ...previous, [name]: value }));
  const save = async () => {
    setSaving(true); setError('');
    try {
      const response = await apiFetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ temperature: values.temperature ?? null, reasoning_effort: values.reasoning_effort || null,
          max_tokens: values.max_tokens || null, inspection_limit: values.inspection_limit }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Settings could not be saved.');
      onClose();
    } catch (failure) { setError(failure.message); }
    finally { setSaving(false); }
  };
  return (
    <dialog ref={dialog} className="model-settings" aria-labelledby="model-settings-title" onCancel={event => { event.preventDefault(); if (!saving) onClose(); }}>
      <header><h2 id="model-settings-title">Model & execution settings</h2><button onClick={onClose} aria-label="Close model settings" disabled={saving}><X size={18} /></button></header>
      {error && <p role="alert" className="changes-error">{error}</p>}
      {!settings ? <p>Loading model capabilities…</p> : <>
        <p className="settings-model">{settings.model}</p>
        <label>Temperature<select aria-label="Temperature" disabled={!settings.capabilities.temperature} value={values.temperature ?? ''} onChange={event => update('temperature', event.target.value === '' ? null : Number(event.target.value))}>
          <option value="">Provider default</option>{[0, 0.2, 0.5, 0.7, 1, 1.5, 2].map(value => <option key={value} value={value}>{value}</option>)}
        </select></label>
        {!settings.capabilities.temperature && <small>The API does not advertise temperature control.</small>}
        <label>Thinking effort<select aria-label="Thinking effort" disabled={!settings.capabilities.effort_tiers.length} value={values.reasoning_effort || ''} onChange={event => update('reasoning_effort', event.target.value)}>
          <option value="">Provider default</option>{settings.capabilities.effort_tiers.map(tier => <option key={tier} value={tier}>{tier}</option>)}
        </select></label>
        {!settings.capabilities.effort_tiers.length && <small>This model does not advertise adjustable thinking effort.</small>}
        <label>Maximum output tokens<input aria-label="Maximum output tokens" type="number" min="128" max={settings.capabilities.max_output_tokens || undefined} disabled={!settings.capabilities.max_output_tokens} placeholder="Provider default" value={values.max_tokens ?? ''} onChange={event => update('max_tokens', event.target.value ? Number(event.target.value) : null)} /></label>
        <label>Inspections before progress warning<input aria-label="Inspection budget" type="number" min="4" max="50" value={values.inspection_limit ?? 12} onChange={event => update('inspection_limit', Number(event.target.value))} /></label>
        <p className="changes-scope">Saved for this model in this workspace. Repeated-output and repeated-inspection protection stay active. Changes apply to the next request.</p>
        <footer><button className="studio-mode" onClick={() => setValues({ inspection_limit: 12 })} disabled={saving}>Reset defaults</button><button className="studio-primary" onClick={save} disabled={saving || isExecuting}>{saving ? 'Saving…' : isExecuting ? 'Task running' : 'Save settings'}</button></footer>
      </>}
    </dialog>
  );
}
