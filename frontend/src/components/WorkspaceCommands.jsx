import React, { useEffect, useRef, useState } from 'react';
import { Search, X } from 'lucide-react';

export default function WorkspaceCommands({ commands, onClose }) {
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState(0);
  const dialog = useRef(null);
  const input = useRef(null);
  const results = commands.filter(command => `${command.label} ${command.detail || ''}`.toLowerCase().includes(query.trim().toLowerCase()));
  const index = Math.min(selected, Math.max(0, results.length - 1));

  useEffect(() => {
    const previousFocus = document.activeElement;
    const element = dialog.current;
    element.showModal();
    input.current.focus();
    return () => {
      element.close();
      if (previousFocus?.isConnected) previousFocus.focus();
    };
  }, []);

  useEffect(() => {
    dialog.current.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' });
  }, [index, query]);

  const run = command => {
    if (!command || command.disabled) return;
    onClose();
    command.run();
  };

  return (
    <dialog ref={dialog} className="workspace-commands" aria-labelledby="workspace-command-title"
      onCancel={event => { event.preventDefault(); onClose(); }}
      onClick={event => { if (event.target === dialog.current) onClose(); }}
      onKeyDown={event => {
        if (event.nativeEvent.isComposing) return;
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
          event.preventDefault();
          setSelected((index + (event.key === 'ArrowDown' ? 1 : -1) + results.length) % (results.length || 1));
        } else if (event.key === 'Enter') {
          event.preventDefault();
          run(results[index]);
        }
      }}>
      <div className="command-search">
        <Search size={18} />
        <input ref={input} role="combobox" aria-label="Search commands and sessions" aria-expanded="true"
          aria-controls="workspace-command-results" aria-activedescendant={results.length ? `workspace-command-${index}` : undefined}
          value={query} onChange={event => { setQuery(event.target.value); setSelected(0); }} placeholder="Search commands and sessions…" />
        <button onClick={onClose} aria-label="Close command palette"><X size={18} /></button>
      </div>
      <h2 id="workspace-command-title">Quick actions & saved sessions</h2>
      <div id="workspace-command-results" role="listbox" aria-label="Commands and sessions" className="command-results">
        {results.map((command, i) => (
          <div key={command.id} id={`workspace-command-${i}`} role="option" aria-selected={i === index}
            aria-disabled={command.disabled || undefined} className="command-result" onClick={() => run(command)}>
            <span>{command.label}<small>{command.detail}</small></span>
            <small>{command.disabled ? 'Task running' : command.kind || 'Action'}</small>
          </div>
        ))}
        {!results.length && <p className="command-empty">No matches. Try a session title, model, or action.</p>}
      </div>
      <footer>↑ ↓ to navigate · Enter to open · Esc to close</footer>
    </dialog>
  );
}
