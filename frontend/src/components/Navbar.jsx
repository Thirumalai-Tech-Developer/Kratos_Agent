import React, { useState } from 'react';
import { 
  Shield, 
  Database, 
  RotateCw, 
  Info, 
  Plus, 
  Menu, 
  X, 
  Zap, 
  Terminal, 
  MessageSquare, 
  Clock, 
  Lock, 
  Unlock,
  Sliders,
  Cpu
} from 'lucide-react';

export default function Navbar({ 
  stats, 
  telemetry, 
  isAgentMode, 
  onToggleAgentMode, 
  onRefresh, 
  onNewSession, 
  onOpenTechSpecs,
  isHudOpen,
  onToggleHud,
  activeTab,
  onSelectTab
}) {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  return (
    <header className="sticky top-0 z-40 w-full glass-panel border-b border-pink-500/20 shadow-[0_4px_30px_rgba(0,0,0,0.5)]">
      <div className="max-w-[1600px] mx-auto px-3 sm:px-5 lg:px-8 w-full">
        <div className="flex items-center justify-between h-16 sm:h-20 gap-1.5 sm:gap-3">
          
          {/* Brand Identity */}
          <div 
            className="flex items-center gap-2 sm:gap-3 cursor-pointer select-none min-w-0 flex-shrink-0" 
            onClick={() => onSelectTab('arena')}
          >
            <div className="relative group flex-shrink-0">
              <div className="absolute -inset-0.5 bg-gradient-to-r from-[#ff007f] to-[#00f3ff] rounded-xl blur opacity-75 group-hover:opacity-100 transition duration-300"></div>
              <img 
                src="/kratos_badge.png" 
                alt="Kratos Agent" 
                className="relative w-9 h-9 sm:w-11 sm:h-11 rounded-xl object-cover border border-white/20 shadow-md"
              />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-1.5 sm:gap-2">
                <span className="font-orbitron font-black text-base sm:text-xl lg:text-2xl tracking-wider text-white whitespace-nowrap">
                  KRATOS <span className="text-vice-pink neon-text-pink">AGENT</span>
                </span>
                <span className="hidden sm:inline-block px-1.5 sm:px-2 py-0.5 text-[9px] sm:text-[10px] font-pixl font-bold uppercase tracking-widest rounded bg-gradient-to-r from-pink-500/20 to-cyan-500/20 border border-pink-500/30 text-pink-300 whitespace-nowrap">
                  VICE CYBERPUNK
                </span>
              </div>
              <p className="text-[10px] sm:text-[11px] font-rajdhani font-medium text-slate-400 hidden xl:block truncate max-w-[240px] 2xl:max-w-none">
                Autonomous Protocol & Cloudflare D1 Intelligence
              </p>
            </div>
          </div>

          {/* Center Telemetry Card (Wide screens) */}
          <div className="hidden xl:flex items-center gap-2.5 px-2.5 py-1 rounded-lg glass-card border border-white/10 flex-shrink-0">
            <div className="flex items-center gap-1.5">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
              </span>
              <span className="text-[11px] font-pixl font-bold tracking-wider text-emerald-400">
                CLOUDFLARE D1
              </span>
            </div>
            <div className="h-3.5 w-px bg-white/10"></div>
            <div className="text-[10px] font-code text-slate-300 flex items-center gap-2">
              <span className="text-slate-500 font-pixl">PING:</span>
              <span className="text-[#00f3ff] font-semibold">{stats?.latency_ms ?? 14}ms</span>
              <span className="text-slate-600">/</span>
              <span className="text-slate-500 font-pixl">DB:</span>
              <span className="text-slate-300 truncate max-w-[70px]">{stats?.database_id ?? 'bound'}</span>
            </div>
          </div>

          {/* Real-time Stats Pills (2XL screens >= 1536px) */}
          <div className="hidden 2xl:flex items-center gap-1.5 text-xs font-rajdhani flex-shrink-0">
            <div className="px-2 py-0.5 rounded-md glass-card flex items-center gap-1 text-slate-300">
              <Database className="w-3.5 h-3.5 text-pink-400" />
              <span className="font-pixl font-bold text-white">{stats?.sessions_count ?? 0}</span>
              <span className="text-[9px] text-slate-400">SESSIONS</span>
            </div>
            <div className="px-2 py-0.5 rounded-md glass-card flex items-center gap-1 text-slate-300">
              <MessageSquare className="w-3.5 h-3.5 text-cyan-400" />
              <span className="font-pixl font-bold text-white">{stats?.turns_count ?? 0}</span>
              <span className="text-[9px] text-slate-400">TURNS</span>
            </div>
            <div className="px-2 py-0.5 rounded-md glass-card flex items-center gap-1 text-slate-300">
              <Zap className="w-3.5 h-3.5 text-amber-400" />
              <span className="font-pixl font-bold text-white">{stats?.events_count ?? 0}</span>
              <span className="text-[9px] text-slate-400">EVENTS</span>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex items-center gap-1.5 sm:gap-2 flex-shrink-0">
            
            {/* Agent Mode Switch */}
            <button
              onClick={onToggleAgentMode}
              className={`relative px-2 sm:px-3 py-1.5 rounded-lg text-[10px] sm:text-xs font-pixl font-bold flex items-center gap-1.5 transition-all duration-300 border flex-shrink-0 ${
                isAgentMode 
                  ? 'bg-pink-600/25 border-pink-500 text-white shadow-[0_0_15px_rgba(255,0,127,0.4)]' 
                  : 'bg-slate-900/60 border-slate-700 text-slate-300 hover:border-slate-500'
              }`}
              title={isAgentMode ? "Agent Mode Active (Autonomous execution enabled)" : "Click to unlock Agent Mode"}
            >
              <span className={`w-1.5 h-1.5 sm:w-2 sm:h-2 rounded-full flex-shrink-0 ${isAgentMode ? 'bg-pink-500 animate-pulse' : 'bg-slate-500'}`}></span>
              {isAgentMode ? (
                <>
                  <Unlock className="w-3 h-3 sm:w-3.5 sm:h-3.5 text-pink-400 flex-shrink-0" />
                  <span className="tracking-wider sm:inline hidden">AGENT: ON</span>
                  <span className="tracking-wider sm:hidden inline">AGENT</span>
                </>
              ) : (
                <>
                  <Lock className="w-3 h-3 sm:w-3.5 sm:h-3.5 text-slate-400 flex-shrink-0" />
                  <span className="tracking-wider sm:inline hidden">NORMAL CHAT</span>
                  <span className="tracking-wider sm:hidden inline">CHAT</span>
                </>
              )}
            </button>

            {/* Quick Actions (Desktop & Tablet) */}
            <button
              onClick={onRefresh}
              className="hidden md:flex p-2 rounded-lg glass-card text-slate-300 hover:text-cyan-400 hover:border-cyan-500/40 transition flex-shrink-0"
              title="Sync latest D1 data"
            >
              <RotateCw className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
            </button>

            <button
              onClick={onOpenTechSpecs}
              className="hidden lg:flex items-center gap-1.5 px-2.5 sm:px-3 py-1.5 rounded-lg glass-card text-xs font-pixl font-bold text-slate-300 hover:text-white hover:border-cyan-500/40 transition flex-shrink-0"
            >
              <Info className="w-3.5 h-3.5 text-cyan-400" />
              <span>TECH SPECS</span>
            </button>

            <button
              onClick={onNewSession}
              className="px-2.5 sm:px-3.5 py-1.5 rounded-lg text-[10px] sm:text-xs font-pixl font-bold flex items-center gap-1 bg-gradient-to-r from-[#ff007f] to-[#ff8c00] text-white shadow-[0_0_15px_rgba(255,0,127,0.3)] hover:shadow-[0_0_20px_rgba(255,0,127,0.5)] transition duration-200 flex-shrink-0"
            >
              <Plus className="w-3 h-3 sm:w-3.5 sm:h-3.5" />
              <span className="hidden xs:inline">NEW RUN</span>
            </button>

            {/* Mobile / Tablet HUD Drawer Toggle */}
            <button
              onClick={onToggleHud}
              className={`lg:hidden p-1.5 sm:p-2 rounded-lg border transition flex-shrink-0 ${
                isHudOpen 
                  ? 'bg-cyan-500/20 border-cyan-400 text-cyan-300' 
                  : 'glass-card text-slate-300 hover:text-cyan-400'
              }`}
              title="Toggle Live HUD Drawer"
            >
              <Cpu className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
            </button>

            {/* Mobile Hamburger */}
            <button
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="md:hidden p-1.5 sm:p-2 rounded-lg glass-card text-slate-300 hover:text-white flex-shrink-0"
              title="Toggle Navigation Menu"
            >
              {mobileMenuOpen ? <X className="w-4 h-4" /> : <Menu className="w-4 h-4" />}
            </button>

          </div>

        </div>
      </div>

      {/* Mobile Drawer Menu */}
      {mobileMenuOpen && (
        <div className="md:hidden glass-panel border-t border-white/10 px-4 py-4 space-y-3 animate-fadeIn">
          {/* Telemetry Status */}
          <div className="flex items-center justify-between p-2.5 rounded-lg bg-black/40 border border-white/10">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
              <span className="text-xs font-rajdhani font-bold text-emerald-400">CLOUDFLARE D1</span>
            </div>
            <div className="text-[11px] font-code text-cyan-300">
              {stats?.latency_ms ?? 14}ms
            </div>
          </div>

          {/* Stats Bar */}
          <div className="grid grid-cols-3 gap-2 text-center text-xs font-rajdhani">
            <div className="p-2 rounded-md bg-black/30 border border-white/5">
              <div className="font-bold text-pink-400 text-sm">{stats?.sessions_count ?? 0}</div>
              <div className="text-[10px] text-slate-400">SESSIONS</div>
            </div>
            <div className="p-2 rounded-md bg-black/30 border border-white/5">
              <div className="font-bold text-cyan-400 text-sm">{stats?.turns_count ?? 0}</div>
              <div className="text-[10px] text-slate-400">TURNS</div>
            </div>
            <div className="p-2 rounded-md bg-black/30 border border-white/5">
              <div className="font-bold text-amber-400 text-sm">{stats?.events_count ?? 0}</div>
              <div className="text-[10px] text-slate-400">EVENTS</div>
            </div>
          </div>

          {/* Mobile Buttons */}
          <div className="flex items-center gap-2 pt-2">
            <button
              onClick={() => { onRefresh(); setMobileMenuOpen(false); }}
              className="flex-1 py-2 rounded-lg glass-card text-xs font-rajdhani font-bold text-slate-300 flex items-center justify-center gap-1.5"
            >
              <RotateCw className="w-3.5 h-3.5 text-cyan-400" />
              <span>SYNC D1</span>
            </button>
            <button
              onClick={() => { onOpenTechSpecs(); setMobileMenuOpen(false); }}
              className="flex-1 py-2 rounded-lg glass-card text-xs font-rajdhani font-bold text-slate-300 flex items-center justify-center gap-1.5"
            >
              <Info className="w-3.5 h-3.5 text-pink-400" />
              <span>TECH SPECS</span>
            </button>
          </div>
        </div>
      )}
    </header>
  );
}
