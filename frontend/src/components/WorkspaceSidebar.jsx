import React, { useEffect } from 'react';
import { Plus, Search, MessageSquare, History, Activity, FileDiff, Database, Briefcase, Settings2, FileText, X, ChevronRight } from 'lucide-react';
import KratosMark from './KratosMark';

const destinations = [
  ['arena', 'Chat', MessageSquare], ['sessions', 'All chats', History], ['traces', 'Activity', Activity],
  ['changes', 'Changes', FileDiff], ['sql', 'Data', Database], ['jobs', 'Jobs', Briefcase],
];

export default function WorkspaceSidebar({ activeTab, sessions = [], activeSessionId, isExecuting, isOpen, onClose,
  onNavigate, onNewChat, onResumeSession, onOpenCommands, onOpenSettings, onOpenInstructions, userProfile, workspaceName }) {
  useEffect(() => {
    if (!isOpen) return;
    const key = event => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('keydown', key);
    return () => document.removeEventListener('keydown', key);
  }, [isOpen, onClose]);
  const navigate = destination => { onNavigate(destination); onClose(); };
  return <>
    {isOpen && <button type="button" className="sidebar-backdrop" aria-label="Close navigation backdrop" onClick={onClose} />}
    <aside className={`workspace-sidebar ${isOpen ? 'is-open' : ''}`} aria-label="Workspace navigation" hidden={!isOpen}>
      <div className="sidebar-brand"><KratosMark size={36} /><span><strong>Kratos</strong><small>Agent workspace</small></span>
        <button className="studio-icon sidebar-close" type="button" onClick={onClose} aria-label="Close navigation"><X size={17} /></button>
      </div>
      <div className="sidebar-start">
        <button className="sidebar-new-chat" type="button" onClick={() => { onNewChat(); onClose(); }} disabled={isExecuting}><Plus size={17} /><span>New chat</span></button>
        <button className="sidebar-search" type="button" onClick={onOpenCommands} aria-label="Search commands and chats"><Search size={15} /><span>Search</span><kbd>Ctrl K</kbd></button>
      </div>
      <nav className="sidebar-navigation" aria-label="Workspace views">
        {destinations.map(([id, label, Icon]) => <button key={id} type="button" aria-current={activeTab === id ? 'page' : undefined}
          onClick={() => navigate(id)}><Icon size={16} /><span>{label}</span></button>)}
      </nav>
      <section className="sidebar-conversations" aria-labelledby="recent-chats-title">
        <div className="sidebar-section-title"><h2 id="recent-chats-title">Recent chats</h2><button type="button" onClick={() => navigate('sessions')} aria-label="Browse all chats"><ChevronRight size={14} /></button></div>
        <div className="sidebar-session-list">
          {sessions.length ? sessions.slice(0, 30).map(session => <button type="button" key={session.session_id}
            aria-current={session.session_id === activeSessionId && activeTab === 'arena' ? 'true' : undefined}
            disabled={isExecuting} title={session.title || session.session_id}
            onClick={() => { onResumeSession(session.session_id); onClose(); }}>
            <span className="sidebar-chat-title">{session.title || 'Untitled chat'}</span>
            {session.last_status && ['running', 'paused', 'failed'].includes(session.last_status) && <span className={`sidebar-chat-state state-${session.last_status}`} aria-label={session.last_status} />}
          </button>) : <p>Your conversations will appear here.</p>}
        </div>
      </section>
      <div className="sidebar-footer">
        <button type="button" onClick={onOpenInstructions}><FileText size={16} /><span>Project instructions</span><small>kratos.md</small></button>
        <button type="button" onClick={onOpenSettings}><Settings2 size={16} /><span>Settings</span></button>
        <div className="sidebar-workspace"><span className="profile-avatar">K</span><span><strong>{workspaceName || 'Your workspace'}</strong><small>User {userProfile}</small></span><span className="workspace-status-dot" title={isExecuting ? 'Task running' : 'Workspace ready'} /></div>
      </div>
    </aside>
  </>;
}
