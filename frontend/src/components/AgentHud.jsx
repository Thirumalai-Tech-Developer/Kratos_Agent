import React, { useState } from 'react';
import { Cpu, Wrench, Terminal, Database, Server, RefreshCw, X, Shield, Search } from 'lucide-react';

export default function AgentHud({
  currentStep,
  activeTool,
  tools,
  onRefreshTools,
  isOpen,
  onClose,
  telemetry
}) {
  const [toolSearch, setToolSearch] = useState('');

  const filteredTools = (tools || []).filter(t => 
    t.name?.toLowerCase().includes(toolSearch.toLowerCase()) ||
    t.description?.toLowerCase().includes(toolSearch.toLowerCase())
  );

  // Determine active step index: 0=Reasoning, 1=Planning, 2=ToolCall, 3=Verifying
  const stepKind = currentStep?.kind || '';
  const isReasoning = stepKind.includes('thought') || stepKind.includes('reason');
  const isPlanning = stepKind.includes('plan');
  const isTool = stepKind.includes('tool');
  const isVerifying = stepKind.includes('verify') || stepKind.includes('test');

  const hudContent = (
    <div className="flex flex-col h-full min-h-0 space-y-3 sm:space-y-4 overflow-y-auto overflow-x-hidden scrollbar-thin pr-1 w-full min-w-0">
      
      {/* Gauge 1: Current Step Meter */}
      <div className="p-4 rounded-xl glass-panel border border-pink-500/20">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-1.5 text-xs font-rajdhani font-bold text-slate-300">
            <Cpu className="w-3.5 h-3.5 text-pink-400" />
            <span>CURRENT AGENT STEP</span>
          </div>
          <span className={`w-2 h-2 rounded-full ${currentStep ? 'bg-pink-500 animate-ping' : 'bg-slate-600'}`}></span>
        </div>

        <div className="p-3 rounded-lg bg-black/40 border border-white/5 mb-3">
          <div className="font-pixl font-bold text-xs uppercase tracking-wider text-pink-300">
            {currentStep?.tag || 'IDLE / READY'}
          </div>
          <div className="text-[11px] font-code text-slate-300 mt-1 line-clamp-2">
            {currentStep?.label || 'Standing by for next instruction.'}
          </div>
        </div>

        {/* 4-Stage Step Progression Color Bars */}
        <div className="grid grid-cols-4 gap-1.5 h-2 rounded-full overflow-hidden bg-slate-900 p-0.5 border border-white/10">
          <div 
            className={`h-full rounded-sm transition-all duration-300 ${isReasoning ? 'bg-pink-500 shadow-[0_0_10px_#ff007f]' : 'bg-slate-800'}`} 
            title="Stage 1: Reasoning Phase"
          />
          <div 
            className={`h-full rounded-sm transition-all duration-300 ${isPlanning ? 'bg-amber-500 shadow-[0_0_10px_#ff8c00]' : 'bg-slate-800'}`} 
            title="Stage 2: Planning Phase"
          />
          <div 
            className={`h-full rounded-sm transition-all duration-300 ${isTool ? 'bg-cyan-400 shadow-[0_0_10px_#00f3ff]' : 'bg-slate-800'}`} 
            title="Stage 3: Tool Execution Phase"
          />
          <div 
            className={`h-full rounded-sm transition-all duration-300 ${isVerifying ? 'bg-emerald-400 shadow-[0_0_10px_#00ff9f]' : 'bg-slate-800'}`} 
            title="Stage 4: Verification Phase"
          />
        </div>
        <div className="flex justify-between text-[9px] font-pixl font-semibold text-slate-500 mt-1 uppercase">
          <span>Think</span>
          <span>Plan</span>
          <span>Tool</span>
          <span>Verify</span>
        </div>
      </div>

      {/* Gauge 2: Active Tool Monitor */}
      <div className="p-4 rounded-xl glass-panel border border-cyan-500/20">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-1.5 text-xs font-rajdhani font-bold text-slate-300">
            <Wrench className="w-3.5 h-3.5 text-cyan-400" />
            <span>ACTIVE TOOL MONITOR</span>
          </div>
          <span className={`px-2 py-0.5 rounded text-[10px] font-pixl font-bold ${
            activeTool ? 'bg-cyan-500/20 border border-cyan-500/40 text-cyan-300 animate-pulse' : 'bg-slate-800 text-slate-500'
          }`}>
            {activeTool ? 'EXECUTING' : 'STANDBY'}
          </span>
        </div>

        <div className="p-3 rounded-lg bg-black/40 border border-white/5 min-h-[50px] flex items-center">
          {activeTool ? (
            <div className="space-y-1 w-full">
              <div className="flex items-center gap-1.5 text-xs font-code font-bold text-cyan-300">
                <span>⚡</span>
                <span className="truncate">{activeTool.name}</span>
              </div>
              <p className="text-[11px] font-code text-slate-400 truncate">
                {activeTool.label || JSON.stringify(activeTool.args || {})}
              </p>
            </div>
          ) : (
            <div className="flex items-center gap-2 text-xs text-slate-500 font-sans">
              <span className="opacity-60">🔧</span>
              <span>No tool currently executing</span>
            </div>
          )}
        </div>
      </div>

      {/* Gauge 3: Registered Tools Arsenal */}
      <div className="p-4 rounded-xl glass-panel border border-white/10 flex-1 flex flex-col min-h-[220px]">
        <div className="flex items-center justify-between mb-2.5">
          <div className="flex items-center gap-1.5 text-xs font-rajdhani font-bold text-slate-300">
            <Terminal className="w-3.5 h-3.5 text-amber-400" />
            <span>TOOLS ARSENAL ({tools?.length || 0})</span>
          </div>
          <button 
            onClick={onRefreshTools}
            className="p-1 rounded text-slate-400 hover:text-white transition" 
            title="Refresh loaded tools"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Search */}
        <div className="relative mb-2">
          <Search className="w-3 h-3 absolute left-2.5 top-2.5 text-slate-500" />
          <input
            type="text"
            placeholder="Search tools..."
            value={toolSearch}
            onChange={(e) => setToolSearch(e.target.value)}
            className="w-full pl-7 pr-2.5 py-1 text-xs rounded-lg bg-black/40 border border-white/10 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-pink-500/50"
          />
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto space-y-1.5 pr-1 max-h-52 scrollbar-thin">
          {filteredTools.length === 0 ? (
            <div className="text-center py-4 text-xs text-slate-500">No tools found</div>
          ) : (
            filteredTools.map((t, idx) => (
              <div 
                key={idx} 
                className="p-2 rounded-lg bg-black/30 border border-white/5 hover:border-pink-500/30 transition text-xs min-w-0 overflow-hidden"
              >
                <div className="flex items-center justify-between gap-1 min-w-0">
                  <span className="font-code font-semibold text-slate-200 text-[11px] truncate min-w-0">
                    {t.name}
                  </span>
                  <span className={`text-[9px] font-rajdhani font-bold px-1.5 py-0.2 rounded uppercase flex-shrink-0 ${
                    t.permission === 'execute' 
                      ? 'bg-amber-500/15 text-amber-400 border border-amber-500/30' 
                      : t.permission === 'write' 
                      ? 'bg-pink-500/15 text-pink-400 border border-pink-500/30' 
                      : 'bg-cyan-500/15 text-cyan-400 border border-cyan-500/30'
                  }`}>
                    {t.permission || 'read'}
                  </span>
                </div>
                <p className="text-[10px] text-slate-400 mt-1 line-clamp-1 truncate min-w-0">
                  {t.description}
                </p>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Gauge 4: System Architecture Telemetry */}
      <div className="p-4 rounded-xl glass-panel border border-white/10 text-xs">
        <div className="text-xs font-rajdhani font-bold text-slate-300 mb-2">
          SYSTEM TELEMETRY
        </div>
        <div className="grid grid-cols-2 gap-2 text-[11px] font-code">
          <div className="p-2 rounded bg-black/40 border border-white/5 min-w-0 overflow-hidden">
            <span className="text-slate-500 block text-[9px]">RUNTIME:</span>
            <span className="text-amber-400 font-semibold truncate block">KratosAutonomous</span>
          </div>
          <div className="p-2 rounded bg-black/40 border border-white/5 min-w-0 overflow-hidden">
            <span className="text-slate-500 block text-[9px]">WORKSPACE:</span>
            <span className="text-slate-300 font-semibold truncate block">Kratos_Agent</span>
          </div>
          <div className="p-2 rounded bg-black/40 border border-white/5 min-w-0 overflow-hidden">
            <span className="text-slate-500 block text-[9px]">STORAGE:</span>
            <span className="text-cyan-400 font-semibold truncate block">Cloudflare D1</span>
          </div>
          <div className="p-2 rounded bg-black/40 border border-white/5 min-w-0 overflow-hidden">
            <span className="text-slate-500 block text-[9px]">GATEWAY:</span>
            <span className="text-emerald-400 font-semibold truncate block">Socket Tunnel</span>
          </div>
        </div>
      </div>

    </div>
  );

  return (
    <>
      {/* Desktop Persistent / Docked Panel */}
      <aside className="hidden lg:block w-72 xl:w-80 flex-shrink-0 h-full min-h-0 min-w-0 overflow-hidden">
        {hudContent}
      </aside>

      {/* Mobile / Tablet Sliding Drawer */}
      {isOpen && (
        <div className="lg:hidden fixed inset-0 z-50 flex justify-end">
          {/* Backdrop */}
          <div 
            className="fixed inset-0 bg-black/70 backdrop-blur-sm"
            onClick={onClose}
          />
          
          {/* Drawer Container */}
          <div className="relative w-full max-w-sm h-full bg-[#0d071a] border-l border-pink-500/20 p-4 shadow-2xl flex flex-col z-10 animate-slideLeft">
            <div className="flex items-center justify-between pb-3 mb-2 border-b border-white/10">
              <span className="font-orbitron font-bold text-sm text-pink-400 tracking-wider">
                ⚡ REAL-TIME AGENT HUD
              </span>
              <button 
                onClick={onClose}
                className="p-1 rounded-lg text-slate-400 hover:text-white"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            
            <div className="flex-1 overflow-hidden">
              {hudContent}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
