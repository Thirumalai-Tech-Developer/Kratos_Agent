import React from 'react';
import { RotateCw, Info, ListChecks, PanelLeft, Plus, Zap, MessageSquare, Search, Maximize2, SlidersHorizontal } from 'lucide-react';
import KratosMark from './KratosMark';

export default function Navbar({ isAgentMode, onToggleAgentMode, onRefresh, onOpenTechSpecs, isHudOpen, onToggleHud,
  onOpenCommands, isExecuting, onOpenSettings, onNewChat, onToggleSidebar, isSidebarOpen, title = 'New chat', activeTab = 'arena' }) {
  return <header className="studio-header">
    <div className="workspace-heading">
      <button className="studio-icon sidebar-toggle" type="button" onClick={onToggleSidebar} aria-label={isSidebarOpen ? 'Hide chats' : 'Show chats'} title={isSidebarOpen ? 'Hide chats' : 'Show chats'} aria-expanded={isSidebarOpen}><PanelLeft size={18} /></button>
      <KratosMark size={25} className="header-mark" title="" />
      <span className="workspace-title" title={title}>{title}</span>
      {isExecuting && <span className="header-running-dot" title="Task running" />}
    </div>
    <div className="studio-actions">
      <button className="studio-icon header-new-chat" type="button" onClick={onNewChat} disabled={isExecuting} title="New chat" aria-label="New chat"><Plus size={18} /></button>
      {activeTab === 'arena' && <button className="studio-mode" onClick={onToggleAgentMode} aria-pressed={isAgentMode}>
        {isAgentMode ? <Zap size={14} /> : <MessageSquare size={14} />}{isAgentMode ? 'Agent mode' : 'Direct chat'}
      </button>}
      <button className="studio-icon studio-command-trigger" onClick={onOpenCommands} title="Search commands and chats (Ctrl+K / ⌘K)" aria-label="Open command palette"><Search size={16} /></button>
      <button className="studio-icon" onClick={onOpenSettings} title="Model and execution settings" aria-label="Model and execution settings"><SlidersHorizontal size={16} /></button>
      <button className="studio-icon" onClick={onRefresh} title="Refresh workspace" aria-label="Refresh workspace"><RotateCw size={16} /></button>
      {window.self !== window.top && <a className="studio-icon header-fullscreen" href={window.location.pathname} target="_top" title="Open workspace full screen" aria-label="Open workspace full screen"><Maximize2 size={16} /></a>}
      <button className="studio-icon header-info" onClick={onOpenTechSpecs} title="Workspace information" aria-label="Workspace information"><Info size={16} /></button>
      {activeTab === 'arena' && <button className="studio-icon studio-panel-toggle" onClick={onToggleHud} title="Show task details in this chat" aria-label="Toggle task details" aria-expanded={isHudOpen}><ListChecks size={18} /></button>}
    </div>
  </header>;
}
