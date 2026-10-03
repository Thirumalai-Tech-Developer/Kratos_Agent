import React, { useEffect, useRef, useState } from 'react';
import { RotateCw, Undo2, FileDiff } from 'lucide-react';
import { apiFetch } from '../api';

async function request(path, options) {
  const response = await apiFetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

export default function ChangesReview({ isExecuting }) {
  const [checkpoints, setCheckpoints] = useState([]);
  const [active, setActive] = useState('');
  const [file, setFile] = useState('');
  const [diff, setDiff] = useState(null);
  const [selected, setSelected] = useState([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const confirmation = useRef(null);
  const checkpoint = checkpoints.find(item => item.id === active);

  const refresh = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await request('/api/changes');
      setCheckpoints(data.checkpoints || []);
      setActive(previous => data.checkpoints.some(item => item.id === previous) ? previous : data.checkpoints[0]?.id || '');
    } catch (failure) { setError(failure.message); }
    finally { setLoading(false); }
  };

  useEffect(() => {
    const timer = setTimeout(refresh, 0);
    return () => clearTimeout(timer);
  }, [isExecuting]);
  useEffect(() => {
    let cancelled = false;
    if (active && file) {
      request(`/api/changes/diff?checkpoint=${encodeURIComponent(active)}&path=${encodeURIComponent(file)}`)
        .then(data => { if (!cancelled) setDiff(data); })
        .catch(failure => { if (!cancelled) setError(failure.message); });
    }
    return () => { cancelled = true; };
  }, [active, file]);

  const restore = async () => {
    confirmation.current.close();
    setRestoring(true);
    setError('');
    try {
      const data = await request('/api/changes/restore', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ checkpoint: active, paths: selected }),
      });
      setSelected([]);
      await refresh();
      setNotice(`Restored ${data.restored.length} file(s) to their state before this task.`);
    } catch (failure) { setError(failure.message); }
    finally { setRestoring(false); }
  };

  return (
    <section className="changes-review">
      <header className="changes-heading">
        <div><h1><FileDiff size={20} /> Task changes</h1><p>Review each task’s edits and restore selected files to their starting state.</p></div>
        <button className="studio-icon" aria-label="Refresh task changes" onClick={refresh} disabled={loading || restoring}><RotateCw size={17} /></button>
      </header>
      {error && <p role="alert" className="changes-error">{error}</p>}
      {notice && <p role="status" className="changes-notice">{notice}</p>}
      {!checkpoints.length ? <div className="changes-empty">{loading ? 'Loading checkpoints…' : 'No task checkpoints yet. Run a task after restarting Studio to capture its changes.'}</div> : (
        <div className="changes-layout">
          <aside className="changes-files">
            <label htmlFor="review-checkpoint">Task checkpoint</label>
            <select id="review-checkpoint" value={active} disabled={restoring} onChange={event => { setActive(event.target.value); setFile(''); setDiff(null); setSelected([]); setNotice(''); }}>
              {checkpoints.map(item => <option key={item.id} value={item.id}>{new Date(item.created_at * 1000).toLocaleString()} · {item.label}</option>)}
            </select>
            <p className="changes-scope">Source files up to 1 MB each; credentials, databases, dependencies and runtime files are excluded.</p>
            {!!checkpoint?.skipped.length && <p className="changes-scope">{checkpoint.skipped.length} file(s) exceeded capture limits or could not be read.</p>}
            <div className="changes-file-list">
              {!checkpoint?.changes.length && <p className="changes-scope">No supported file changes in this task.</p>}
              {checkpoint?.changes.map(item => (
                <div key={item.path} className={`changes-file ${file === item.path ? 'is-active' : ''}`}>
                  <input type="checkbox" aria-label={`Select ${item.path} for restore`} checked={selected.includes(item.path)} disabled={item.restored || restoring || isExecuting}
                    onChange={event => setSelected(previous => event.target.checked ? [...previous, item.path] : previous.filter(path => path !== item.path))} />
                  <button onClick={() => { setError(''); setDiff(null); setFile(item.path); }}><span>{item.path}</span><small>{item.restored ? 'Restored' : item.kind}</small></button>
                </div>
              ))}
            </div>
            <button className="studio-primary" disabled={!selected.length || restoring || isExecuting} onClick={() => confirmation.current.showModal()}><Undo2 size={16} /> Restore {selected.length || ''} selected</button>
            {isExecuting && <p className="changes-scope">Restoring is available when the task finishes.</p>}
          </aside>
          <div className="changes-diff">
            <header>{file || 'Select a file to inspect its diff'}</header>
            {!file ? <p className="changes-empty">Added lines appear in green; removed lines in red.</p> : !diff ? <p className="changes-empty">Loading diff…</p> : diff.binary ? <p className="changes-empty">Binary file changed. Its saved bytes can be restored.</p> : (
              <pre aria-label={`Diff for ${file}`}><code>{diff.diff.split('\n').map((line, index) => <span key={index} className={line.startsWith('+') ? 'diff-added' : line.startsWith('-') ? 'diff-removed' : line.startsWith('@@') ? 'diff-hunk' : ''}>{line || ' '}<br /></span>)}</code></pre>
            )}
            {diff?.truncated && <p className="changes-scope">Preview limited to 6,000 lines. The complete saved file is used for restoration.</p>}
          </div>
        </div>
      )}
      <dialog ref={confirmation} className="changes-confirm" aria-labelledby="restore-title">
        <h2 id="restore-title">Restore {selected.length} selected file(s)?</h2>
        <p>This restores their saved state before this task. Files created by the task will be removed. If any selected file changed afterward, restoration stops.</p>
        <div><button className="studio-mode" onClick={() => confirmation.current.close()}>Cancel</button><button className="studio-primary" onClick={restore}>Restore files</button></div>
      </dialog>
    </section>
  );
}
