import React from 'react';
import { Bot, RotateCw, Info, Plus, PanelRight, Zap, MessageSquare, Search, Maximize2, SlidersHorizontal } from 'lucide-react';

export default function Navbar({ isAgentMode, onToggleAgentMode, onRefresh, onNewSession, onOpenTechSpecs, isHudOpen, onToggleHud, onSelectTab, onOpenCommands, isExecuting, onOpenSettings }) {
  return (
    <header className="studio-header">
      <button className="studio-brand" onClick={() => onSelectTab('arena')} aria-label="Open Kratos workspace">
        <span className="studio-mark"><Bot size={23} /></span>
        <span><strong>Kratos</strong><small>Your agent workspace</small></span>
      </button>
      <div className="studio-actions">
        <button className="studio-icon" onClick={onOpenSettings} title="Model and execution settings" aria-label="Model and execution settings"><SlidersHorizontal size={17} /></button>
        {window.self !== window.top && <a className="studio-icon" href={window.location.pathname} target="_top" title="Open workspace full screen" aria-label="Open workspace full screen"><Maximize2 size={17} /></a>}
        <button className="studio-icon studio-command-trigger" onClick={onOpenCommands} title="Search commands and sessions (Ctrl+K / ⌘K)" aria-label="Open command palette"><Search size={17} /></button>
        <button className="studio-mode" onClick={onToggleAgentMode} aria-pressed={isAgentMode}>
          {isAgentMode ? <Zap size={15} /> : <MessageSquare size={15} />}
          {isAgentMode ? 'Agent mode' : 'Direct chat'}
        </button>
        <button className="studio-icon" onClick={onRefresh} title="Refresh workspace" aria-label="Refresh workspace"><RotateCw size={17} /></button>
        <button className="studio-icon" onClick={onOpenTechSpecs} title="Workspace information" aria-label="Workspace information"><Info size={17} /></button>
        <button className="studio-icon studio-panel-toggle" onClick={onToggleHud} aria-label="Toggle task details" aria-expanded={isHudOpen}><PanelRight size={17} /></button>
        <button className="studio-primary" onClick={onNewSession} disabled={isExecuting}><Plus size={16} /><span>New task</span></button>
      </div>
    </header>
  );
}
