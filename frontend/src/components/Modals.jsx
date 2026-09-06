import React, { useState } from 'react';
import { Shield, Lock, Eye, EyeOff, X, Copy, Check, Info, Cpu, Database, Zap, Code } from 'lucide-react';

export function AgentAuthModal({ isOpen, onClose, onAuthenticate, error }) {
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = (e) => {
    e.preventDefault();
    onAuthenticate(password);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fadeIn">
      <div className="relative w-full max-w-md rounded-2xl glass-panel border border-pink-500/40 p-6 shadow-[0_0_40px_rgba(255,0,127,0.3)]">
        
        {/* Header */}
        <div className="flex items-center justify-between pb-3 mb-4 border-b border-white/10">
          <div className="flex items-center gap-2">
            <Shield className="w-5 h-5 text-pink-400" />
            <h3 className="font-orbitron font-bold text-sm text-white tracking-wider">
              COMMANDER SECURITY CLEARANCE
            </h3>
          </div>
          <button 
            onClick={onClose}
            className="p-1 rounded-lg text-slate-400 hover:text-white"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="text-center py-2">
            <div className="w-12 h-12 rounded-2xl bg-pink-950/40 border border-pink-500/40 flex items-center justify-center mx-auto mb-2 text-pink-400 shadow-[0_0_15px_rgba(255,0,127,0.3)]">
              <Lock className="w-6 h-6" />
            </div>
            <h4 className="font-orbitron font-bold text-sm text-pink-300">
              AUTONOMOUS AGENT MODE LOCKED
            </h4>
            <p className="text-xs text-slate-400 mt-1">
              Autonomous file modifications and terminal command execution require Commander Authorization Passcode.
            </p>
          </div>

          <div className="space-y-1.5">
            <label className="block text-xs font-rajdhani font-bold text-slate-300">
              COMMANDER PASSCODE:
            </label>
            <div className="relative">
              <input
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter passcode (default: kratos)..."
                autoFocus
                className="w-full px-3.5 py-2.5 rounded-xl bg-black/60 border border-slate-700 text-sm text-white focus:outline-none focus:border-pink-500/80 pr-10 font-code"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute right-3 top-2.5 text-slate-400 hover:text-white"
              >
                {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          {error && (
            <div className="p-2.5 rounded-lg bg-red-950/50 border border-red-500/50 text-xs text-red-300 font-semibold text-center animate-shake">
              {error}
            </div>
          )}

          <div className="flex items-center gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 py-2 rounded-xl glass-card text-xs font-rajdhani font-bold text-slate-300 hover:text-white transition"
            >
              CANCEL
            </button>
            <button
              type="submit"
              className="flex-1 py-2 rounded-xl bg-gradient-to-r from-[#ff007f] to-[#ff8c00] text-xs font-rajdhani font-bold text-white shadow-[0_0_15px_rgba(255,0,127,0.4)] hover:shadow-[0_0_20px_rgba(255,0,127,0.6)] transition"
            >
              UNLOCK & ACTIVATE
            </button>
          </div>

          <div className="text-center text-[10px] font-code text-slate-500">
            Default clearance passcode: <span className="text-pink-400">kratos</span>
          </div>
        </form>

      </div>
    </div>
  );
}

export function TechSpecsModal({ isOpen, onClose }) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fadeIn">
      <div className="relative w-full max-w-2xl rounded-2xl glass-panel border border-cyan-500/40 p-6 sm:p-8 shadow-[0_0_50px_rgba(0,243,255,0.2)] max-h-[90vh] overflow-y-auto scrollbar-thin">
        
        {/* Header */}
        <div className="flex items-center justify-between pb-4 mb-6 border-b border-white/10">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-cyan-950/40 border border-cyan-500/40 text-cyan-400">
              <Info className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-orbitron font-black text-lg text-white">
                KRATOS AGENT · RECRUITER ARCHITECTURE
              </h3>
              <p className="text-xs font-rajdhani text-cyan-300">
                Vice City Cyberpunk Protocol Specifications
              </p>
            </div>
          </div>
          <button onClick={onClose} className="p-1 rounded-lg text-slate-400 hover:text-white">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Grid Specs */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="p-4 rounded-xl glass-card border border-pink-500/20">
            <div className="flex items-center gap-2 mb-2 text-pink-400 font-rajdhani font-bold text-sm">
              <Cpu className="w-4 h-4" />
              <span>Autonomous Multi-Stage Loop</span>
            </div>
            <p className="text-xs text-slate-300 leading-relaxed">
              Implements multi-step reasoning, intent classification, dynamic plan formulation, surgical file diffs, and self-healing test verification without human intervention.
            </p>
          </div>

          <div className="p-4 rounded-xl glass-card border border-cyan-500/20">
            <div className="flex items-center gap-2 mb-2 text-cyan-400 font-rajdhani font-bold text-sm">
              <Database className="w-4 h-4" />
              <span>Cloudflare D1 Serverless DB</span>
            </div>
            <p className="text-xs text-slate-300 leading-relaxed">
              Relational SQLite deployed globally on Cloudflare's edge network. Zero heavy drivers; connects via secure REST API with automatic local SQLite mirror fallback.
            </p>
          </div>

          <div className="p-4 rounded-xl glass-card border border-amber-500/20">
            <div className="flex items-center gap-2 mb-2 text-amber-400 font-rajdhani font-bold text-sm">
              <Zap className="w-4 h-4" />
              <span>Real-Time SSE Streaming</span>
            </div>
            <p className="text-xs text-slate-300 leading-relaxed">
              Server-Sent Events tracking tool calls, thinking tokens, file inspections, and command outputs live with millisecond latency.
            </p>
          </div>

          <div className="p-4 rounded-xl glass-card border border-emerald-500/20">
            <div className="flex items-center gap-2 mb-2 text-emerald-400 font-rajdhani font-bold text-sm">
              <Code className="w-4 h-4" />
              <span>Modern React + Vite Frontend</span>
            </div>
            <p className="text-xs text-slate-300 leading-relaxed">
              Ultra-responsive layout built with Tailwind CSS, Lucide icons, full mobile drawer support, and high-performance Markdown syntax highlighting.
            </p>
          </div>
        </div>

        <div className="mt-6 pt-4 border-t border-white/10 flex justify-end">
          <button
            onClick={onClose}
            className="px-5 py-2 rounded-xl bg-slate-800 text-white font-rajdhani font-bold text-xs hover:bg-slate-700 transition"
          >
            CLOSE BRIEF
          </button>
        </div>

      </div>
    </div>
  );
}

export function PayloadModal({ isOpen, onClose, event }) {
  const [copied, setCopied] = useState(false);

  if (!isOpen || !event) return null;

  let formattedJson = '';
  try {
    const payload = typeof event.payload_json === 'string' ? JSON.parse(event.payload_json) : event.payload_json;
    formattedJson = JSON.stringify(payload, null, 2);
  } catch (_) {
    formattedJson = String(event.payload_json || '');
  }

  const handleCopy = () => {
    navigator.clipboard.writeText(formattedJson);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fadeIn">
      <div className="relative w-full max-w-xl rounded-2xl glass-panel border border-cyan-500/30 p-6 shadow-2xl max-h-[85vh] flex flex-col">
        
        {/* Header */}
        <div className="flex items-center justify-between pb-3 mb-3 border-b border-white/10">
          <div>
            <h3 className="font-orbitron font-bold text-sm text-white">
              EVENT PAYLOAD INSPECTOR
            </h3>
            <p className="text-xs font-code text-cyan-400 mt-0.5">
              Kind: {event.kind} · ID: {event.id ? event.id.slice(0, 16) : 'N/A'}
            </p>
          </div>
          <button onClick={onClose} className="p-1 rounded-lg text-slate-400 hover:text-white">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Code Content */}
        <div className="flex-1 overflow-auto rounded-xl bg-slate-950 p-4 border border-slate-800 font-code text-xs text-pink-300 scrollbar-thin">
          <pre><code>{formattedJson}</code></pre>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between pt-4 mt-2 border-t border-white/10">
          <button
            onClick={handleCopy}
            className="px-3 py-1.5 rounded-lg text-xs font-code flex items-center gap-1.5 bg-slate-800 text-slate-300 hover:text-white transition"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
            <span>{copied ? 'Copied JSON!' : 'Copy Payload'}</span>
          </button>

          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-lg bg-pink-600 text-white font-rajdhani font-bold text-xs hover:bg-pink-500 transition"
          >
            Done
          </button>
        </div>

      </div>
    </div>
  );
}
