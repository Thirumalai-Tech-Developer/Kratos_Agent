import React, { useCallback, useEffect, useRef, useState } from 'react';
import { FileText, LoaderCircle, RotateCw, Save, X } from 'lucide-react';
import { apiFetch } from '../api';

export default function ProjectInstructions({ isExecuting, onClose }) {
  const dialog = useRef(null);
  const alive = useRef(false);
  const request = useRef(null);
  const [record, setRecord] = useState(null);
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [conflict, setConflict] = useState(false);
  const [showSavedVersion, setShowSavedVersion] = useState(false);
  const load = useCallback(async (preserveDraft = false) => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    try {
      const response = await apiFetch('/api/project/instructions', { signal: controller.signal });
      const data = await response.json().catch(() => ({}));
      if (!alive.current || controller.signal.aborted) return;
      if (!response.ok) throw new Error(data.error || 'Project instructions could not be loaded.');
      setRecord(data);
      if (!preserveDraft) setContent(data.content || '');
      setError(data.error || '');
      setConflict(false);
      setShowSavedVersion(preserveDraft);
      if (preserveDraft) setNotice('Loaded the saved version below. Your draft is still in the editor; review it before saving.');
    } catch (failure) {
      if (alive.current && !controller.signal.aborted) setError(failure.message || 'Project instructions could not be loaded.');
    } finally {
      if (alive.current && !controller.signal.aborted && request.current === controller) {
        setLoading(false);
        request.current = null;
      }
    }
  }, []);
  useEffect(() => {
    const previous = document.activeElement;
    const element = dialog.current;
    alive.current = true;
    element.showModal();
    load();
    return () => {
      alive.current = false;
      request.current?.abort();
      element.close();
      if (previous?.isConnected) previous.focus();
    };
  }, [load]);
  const bytes = new TextEncoder().encode(content).length;
  const overLimit = bytes > (record?.max_bytes || 65536);
  const save = async () => {
    if (isExecuting || saving || loading || !record || record.error || overLimit || conflict) return;
    const controller = new AbortController();
    request.current = controller;
    setSaving(true); setError(''); setNotice('');
    try {
      const response = await apiFetch('/api/project/instructions', {
        method: 'POST', signal: controller.signal, headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content, expected_digest: record.digest ?? null }),
      });
      const data = await response.json().catch(() => ({}));
      if (!alive.current || controller.signal.aborted) return;
      if (!response.ok) {
        if (response.status === 409) setConflict(true);
        throw new Error(data.error || 'Instructions could not be saved (' + response.status + ').');
      }
      setRecord(data); setContent(data.content ?? content); setShowSavedVersion(false);
      setNotice(data.message || 'Saved. Project instructions apply to your next message.');
    } catch (failure) {
      if (alive.current && !controller.signal.aborted) setError(failure.message || 'Instructions could not be saved.');
    } finally {
      if (alive.current && !controller.signal.aborted) setSaving(false);
      if (request.current === controller) request.current = null;
    }
  };
  return <dialog ref={dialog} className="project-instructions" aria-labelledby="instructions-title"
    onCancel={event => { event.preventDefault(); if (!saving) onClose(); }}>
    <header><div><FileText size={19} /><h2 id="instructions-title">Project instructions</h2></div><button className="studio-icon" onClick={onClose} disabled={saving} aria-label="Close project instructions"><X size={18} /></button></header>
    <p>Save the project’s conventions and preferences in <code>{record?.relative_path || 'kratos.md'}</code>. Kratos reads them for each new request.</p>
    {loading ? <p className="instructions-loading"><LoaderCircle size={16} className="animate-spin" />Loading instructions…</p> : <>
      <label htmlFor="instructions-content">{record?.exists ? 'Current instructions' : 'Create project instructions'}</label>
      <textarea id="instructions-content" spellCheck={false} value={content} onChange={event => { setContent(event.target.value); setNotice(''); }}
        placeholder="Project conventions, preferred tools, and how work should be verified…" disabled={isExecuting || saving || !record || Boolean(record.error)} />
      <small>{bytes.toLocaleString()} / {(record?.max_bytes || 65536).toLocaleString()} bytes · {record?.loaded ? 'Loaded by Kratos' : record?.exists ? 'Saved in project' : 'No file yet'}</small>
    </>}
    {(error || overLimit) && <p className="instructions-error" role="alert">{overLimit ? 'Instructions exceed the file size limit.' : error}</p>}
    {(conflict || record?.error || (!record && !loading)) && <button className="studio-mode" type="button" disabled={loading || saving} onClick={() => { setLoading(true); load(true); }}><RotateCw size={14} />Reload saved instructions</button>}
    {showSavedVersion && record && <details className="instructions-saved-version"><summary>Current saved instructions</summary><pre>{record.content || 'No saved instructions.'}</pre></details>}
    {isExecuting && <p className="instructions-notice" role="status">Finish or stop the current task before editing project instructions.</p>}
    {notice && <p className="instructions-notice" role="status">{notice}</p>}
    <footer><button className="studio-mode" onClick={onClose} disabled={saving}>Close</button><button className="studio-primary" onClick={save}
      disabled={loading || saving || isExecuting || !record || Boolean(record.error) || overLimit || conflict || (record.exists && content === record.content)}>{saving ? <LoaderCircle size={15} className="animate-spin" /> : <Save size={15} />}Save instructions</button></footer>
  </dialog>;
}
