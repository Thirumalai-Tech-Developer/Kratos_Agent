import React, { useState } from 'react';
import { Search, Database, MessageSquare, Trash2, CornerUpRight, Clock, ShieldCheck, User } from 'lucide-react';
import MarkdownRenderer from './MarkdownRenderer';

export default function SessionsExplorer({
  sessions,
  activeSessionId,
  activeSessionData,
  onSelectSession,
  onResumeSession,
  onDeleteSession,
  isLoading
}) {
  const [search, setSearch] = useState('');

  const filteredSessions = (sessions || []).filter(s =>
    (s.title || s.session_id || '').toLowerCase().includes(search.toLowerCase()) ||
    (s.model || '').toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="flex flex-col md:flex-row h-full gap-4 rounded-2xl overflow-hidden">
      
      {/* Left Column: Search & Sessions List */}
      <aside className="w-full md:w-80 xl:w-96 flex-shrink-0 flex flex-col glass-panel rounded-2xl border border-pink-500/20 p-4 shadow-xl">
        <div className="flex items-center justify-between pb-3 mb-3 border-b border-white/10">
          <div className="flex items-center gap-2 text-xs font-rajdhani font-bold text-slate-300">
            <Database className="w-4 h-4 text-pink-400" />
            <span>CLOUDFLARE D1 SESSIONS ({sessions?.length || 0})</span>
          </div>
        </div>

        {/* Search Input */}
        <div className="relative mb-3">
          <Search className="w-3.5 h-3.5 absolute left-3 top-3 text-slate-500" />
          <input
            type="text"
            placeholder="Search sessions..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-3 py-2 text-xs rounded-xl bg-black/50 border border-white/10 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-pink-500/50"
          />
        </div>

        {/* Sessions List */}
        <div className="flex-1 overflow-y-auto space-y-2 pr-1 scrollbar-thin">
          {isLoading ? (
            <div className="p-6 text-center text-xs text-slate-500">Loading sessions from D1...</div>
          ) : filteredSessions.length === 0 ? (
            <div className="p-6 text-center text-xs text-slate-500">No sessions found in D1</div>
          ) : (
            filteredSessions.map((s) => {
              const isSelected = s.session_id === activeSessionId;
              return (
                <div
                  key={s.session_id}
                  onClick={() => onSelectSession(s.session_id)}
                  className={`p-3 rounded-xl cursor-pointer transition duration-200 border ${
                    isSelected
                      ? 'bg-gradient-to-r from-pink-950/40 to-slate-900 border-pink-500/50 shadow-[0_0_15px_rgba(255,0,127,0.2)]'
                      : 'bg-black/30 border-white/5 hover:border-pink-500/30'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-semibold text-xs text-white truncate">
                      {s.title || 'Untitled Session'}
                    </span>
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-code bg-black/40 text-cyan-300 border border-white/10">
                      {s.turns_count ?? 0} turns
                    </span>
                  </div>

                  <div className="flex items-center justify-between text-[10px] font-code text-slate-400 mt-2">
                    <span className="truncate max-w-[130px]">{s.model || 'auto'}</span>
                    <span>{s.updated_at ? new Date(s.updated_at).toLocaleDateString() : 'recent'}</span>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </aside>

      {/* Right Column: Session Detail & Turns Stream */}
      <div className="flex-1 flex flex-col glass-panel rounded-2xl border border-pink-500/20 overflow-hidden shadow-xl">
        
        {/* Active Session Hero Bar */}
        <div className="p-4 sm:p-5 bg-[#0e071c] border-b border-pink-500/15 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="font-orbitron font-bold text-lg text-white">
                {activeSessionData?.session?.title || (activeSessionId ? `Session ${activeSessionId.slice(0, 16)}` : 'Select a Session')}
              </h2>
            </div>

            <div className="flex flex-wrap items-center gap-2 mt-2 text-[11px] font-code">
              {activeSessionData?.session?.model && (
                <span className="px-2 py-0.5 rounded bg-pink-950/40 border border-pink-500/30 text-pink-300">
                  Model: {activeSessionData.session.model}
                </span>
              )}
              {activeSessionData?.session?.last_status && (
                <span className="px-2 py-0.5 rounded bg-cyan-950/40 border border-cyan-500/30 text-cyan-300">
                  Status: {activeSessionData.session.last_status}
                </span>
              )}
              {activeSessionId && (
                <span className="px-2 py-0.5 rounded bg-slate-900 border border-white/10 text-slate-400 truncate max-w-[200px]">
                  ID: {activeSessionId}
                </span>
              )}
            </div>
          </div>

          {activeSessionId && (
            <div className="flex items-center gap-2 self-end sm:self-auto">
              <button
                onClick={() => onResumeSession(activeSessionId)}
                className="px-3 py-1.5 rounded-lg font-rajdhani font-bold text-xs flex items-center gap-1.5 bg-cyan-500/20 border border-cyan-400 text-cyan-300 hover:bg-cyan-500/30 hover:shadow-[0_0_15px_rgba(0,243,255,0.4)] transition"
              >
                <CornerUpRight className="w-3.5 h-3.5" />
                <span>CONTINUE IN ARENA</span>
              </button>

              <button
                onClick={() => onDeleteSession(activeSessionId)}
                className="p-1.5 rounded-lg text-slate-400 hover:text-red-400 hover:bg-red-950/30 border border-transparent hover:border-red-500/30 transition"
                title="Delete session"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          )}
        </div>

        {/* Turns Conversation View */}
        <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-6 scrollbar-thin">
          {!activeSessionId ? (
            <div className="flex flex-col items-center justify-center h-full text-center text-slate-500 py-12">
              <Database className="w-12 h-12 text-slate-600 mb-3" />
              <h3 className="font-orbitron font-bold text-sm text-slate-400">No session selected</h3>
              <p className="text-xs text-slate-500 mt-1 max-w-sm">
                Select a session from the list on the left to inspect stored conversation turns and tool executions.
              </p>
            </div>
          ) : !activeSessionData?.turns?.length ? (
            <div className="flex flex-col items-center justify-center h-full text-center text-slate-500 py-12">
              <MessageSquare className="w-12 h-12 text-slate-600 mb-3" />
              <h3 className="font-orbitron font-bold text-sm text-slate-400">No turns recorded</h3>
              <p className="text-xs text-slate-500 mt-1">
                Click "CONTINUE IN ARENA" above to send instructions to this session.
              </p>
            </div>
          ) : (
            activeSessionData.turns.map((turn, tIdx) => (
              <div key={turn.id || tIdx} className="space-y-3">
                {/* User Turn */}
                <div className="flex justify-end gap-3">
                  <div className="max-w-[85%] rounded-2xl p-4 bg-gradient-to-br from-[#1d0d33] to-[#120822] border border-pink-500/30 rounded-tr-sm text-sm text-slate-100">
                    <div className="flex items-center gap-1.5 text-[11px] font-rajdhani font-bold text-pink-400 mb-1">
                      <User className="w-3.5 h-3.5" />
                      <span>COMMANDER (Turn {turn.turn_index ?? tIdx + 1})</span>
                    </div>
                    <p className="leading-relaxed">{turn.user_query}</p>
                  </div>
                </div>

                {/* Agent Turn */}
                <div className="flex justify-start gap-3">
                  <div className="flex-shrink-0 mt-1">
                    <img 
                      src="/kratos_badge.png" 
                      alt="Kratos" 
                      className="w-8 h-8 rounded-xl object-cover border border-pink-500/40 shadow-sm"
                    />
                  </div>
                  <div className="max-w-[85%] rounded-2xl p-4 glass-card border border-slate-700/60 rounded-tl-sm text-sm text-slate-100">
                    <div className="flex items-center gap-1.5 text-[11px] font-rajdhani font-bold text-cyan-400 mb-2">
                      <span>⚔️</span>
                      <span>KRATOS AGENT // STORED REPLY</span>
                    </div>
                    <MarkdownRenderer content={turn.agent_reply} />
                  </div>
                </div>
              </div>
            ))
          )}
        </div>

      </div>

    </div>
  );
}
