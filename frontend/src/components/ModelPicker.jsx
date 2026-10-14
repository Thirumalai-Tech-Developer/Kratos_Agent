import React, { useEffect, useRef, useState } from 'react';
import { Check, ChevronRight, LoaderCircle, RefreshCw, Search, X } from 'lucide-react';
import { apiFetch } from '../api';
import { groupModelCatalog, modelModalityLabel } from '../modelCatalog';

export default function ModelPicker({ currentModel, models = [], catalogLoaded = false, loading = false,
  catalogError = '', notices = [], onRefetch, isExecuting, onSelected, onClose }) {
  const dialog = useRef(null);
  const input = useRef(null);
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const [saving, setSaving] = useState(false);
  const [requestedModel, setRequestedModel] = useState('');
  const [error, setError] = useState('');
  const groups = groupModelCatalog(models, query);
  const results = groups.flatMap(group => group.models);
  const index = Math.min(activeIndex, Math.max(0, results.length - 1));

  useEffect(() => {
    const previousFocus = document.activeElement;
    const element = dialog.current;
    element.showModal();
    input.current.focus();
    return () => { element.close(); if (previousFocus?.isConnected) previousFocus.focus(); };
  }, []);

  useEffect(() => {
    dialog.current.querySelector('[data-highlighted="true"]')?.scrollIntoView({ block: 'nearest' });
  }, [index, query, loading]);

  const selectModel = async model => {
    if (!model || model.disabled || saving || loading || isExecuting) return;
    if (model.id === currentModel && (!model.selection_key || model.is_configured)) { onClose(); return; }
    setSaving(true);
    setRequestedModel(model.id);
    setError('');
    try {
      const response = await apiFetch('/api/models', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model: model.id,
          ...(model.selection_key ? { connection: model.selection_key } : {}) }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || `The model could not be changed (${response.status}).`);
      if (typeof data.model !== 'string' || !data.model) throw new Error('The runtime did not confirm the model change. Refetch the catalog to check it.');
      await onSelected(data.model, typeof data.selection_key === 'string' ? data.selection_key : model.selection_key);
      onClose();
    } catch (failure) {
      setError(failure.message || 'The model could not be changed.');
      setSaving(false);
      setRequestedModel('');
    }
  };

  let rowIndex = 0;
  return (
    <dialog ref={dialog} className="model-picker" aria-labelledby="model-picker-title" aria-describedby="model-picker-description"
      onCancel={event => { event.preventDefault(); if (!saving) onClose(); }}
      onClick={event => { if (event.target === dialog.current && !saving) onClose(); }}>
      <header>
        <div><h2 id="model-picker-title">Choose a model</h2><p id="model-picker-description">Use this model for your next request.</p></div>
        <button className="studio-icon" onClick={onClose} disabled={saving} aria-label="Close model picker"><X size={18} /></button>
      </header>
      <div className="model-picker-current"><span>Current model</span><strong>{currentModel || 'Auto'}</strong></div>
      <div className="model-picker-search">
        <Search size={18} />
        <input ref={input} role="combobox" aria-label="Search models and providers" aria-expanded="true"
          aria-controls="model-picker-results" aria-autocomplete="list" aria-activedescendant={!loading && results.length ? `model-picker-option-${index}` : undefined}
          placeholder="Search models or providers…" value={query} disabled={saving}
          onChange={event => { setQuery(event.target.value); setActiveIndex(0); }}
          onKeyDown={event => {
            if (event.nativeEvent.isComposing || saving || loading) return;
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
              event.preventDefault();
              setActiveIndex((index + (event.key === 'ArrowDown' ? 1 : -1) + results.length) % (results.length || 1));
            } else if (event.key === 'Enter') { event.preventDefault(); selectModel(results[index]); }
          }} />
        <button className="studio-icon model-picker-refetch" onClick={() => { setError(''); setActiveIndex(0); onRefetch?.(); }} disabled={loading || saving}
          aria-label="Refetch available models" title="Refetch available models"><RefreshCw size={16} className={loading ? 'animate-spin' : ''} /><span>Refetch</span></button>
      </div>
      {(error || catalogError) && <p role="alert" className="model-picker-error">{error || catalogError}</p>}
      {notices.map(message => <p key={message} className="model-picker-notice" role="status">{message}</p>)}
      {isExecuting && <p className="model-picker-notice" role="status">Wait for the current task to finish before changing models.</p>}
      <div id="model-picker-results" className="model-picker-results" role="listbox" aria-label="Available models" aria-busy={loading || saving}>
        {loading && !catalogLoaded ? <p className="model-picker-empty" role="status"><LoaderCircle size={16} className="animate-spin" />Loading models…</p> : groups.map((group, groupIndex) => (
          <section key={group.provider} role="group" aria-labelledby={`model-provider-${groupIndex}`}>
            <h3 id={`model-provider-${groupIndex}`}>{group.provider}<span>{group.models.length}</span></h3>
            {group.models.map(model => {
              const optionIndex = rowIndex++;
              const selected = model.id === currentModel && (!model.selection_key || model.is_configured);
              const blocked = model.disabled || isExecuting || saving || loading;
              return <button key={model.selection_key || model.id} type="button" role="option" tabIndex={-1} id={`model-picker-option-${optionIndex}`}
                className="model-picker-option" aria-selected={selected} aria-disabled={blocked || undefined}
                data-highlighted={index === optionIndex} onMouseMove={() => { if (!saving) setActiveIndex(optionIndex); }}
                onClick={() => selectModel(model)} title={model.disabledReason || model.id}>
                <span className="model-option-icon">{saving && requestedModel === model.id ? <LoaderCircle size={17} className="animate-spin" /> : selected ? <Check size={17} /> : <ChevronRight size={16} />}</span>
                <span className="model-option-name"><strong>{model.name}<span className="model-modality-label">{modelModalityLabel(model)}</span></strong><small>{model.id}{model.connection_label ? ` · ${model.connection_label}` : ''}</small>{model.disabled && <small className="model-option-unavailable">{model.disabledReason || 'Unavailable for this account'}</small>}</span>
                {selected && <span className="model-option-selected">Selected</span>}
              </button>;
            })}
          </section>
        ))}
        {!loading && !results.length && <p className="model-picker-empty">{models.length ? 'No models match your search.' : error || catalogError ? 'Refetch the catalog to try again.' : 'No models are available. Connect a provider to add models.'}</p>}
      </div>
      <footer><span aria-live="polite">{saving ? 'Changing model…' : loading ? (catalogLoaded ? 'Refetching catalog…' : 'Loading catalog') : `${results.length} ${results.length === 1 ? 'model' : 'models'}`}</span><small>↑ ↓ navigate · Enter select · Esc close</small></footer>
    </dialog>
  );
}
