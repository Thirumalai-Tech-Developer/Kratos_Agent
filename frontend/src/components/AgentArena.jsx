import React, { useRef, useEffect, useState } from 'react';
import { Send, Trash2, Shield, Zap, Sparkles, Terminal, CornerDownLeft, Bot, User, ChevronDown } from 'lucide-react';
import MarkdownRenderer from './MarkdownRenderer';

function ReasoningAccordion({ reasoning, isThinking, duration }) {
  const [isOpen, setIsOpen] = useState(isThinking || false);

  useEffect(() => {
    if (isThinking) {
      setIsOpen(true);
    }
  }, [isThinking]);

  if (!reasoning && !isThinking) return null;

  return (
    <div className="reasoning-box mb-3 rounded-xl border border-cyan-500/25 bg-[#0a1120]/70 overflow-hidden shadow-[0_2px_12px_rgba(0,0,0,0.3)] transition-all">
      <button
        type="button"
        onClick={() => setIsOpen((prev) => !prev)}
        className="w-full flex items-center justify-between px-3.5 py-2 text-left bg-black/40 hover:bg-cyan-950/40 transition-colors cursor-pointer select-none group"
      >
        <div className="flex items-center gap-2 text-xs font-rajdhani font-semibold text-cyan-300">
          <span className={`inline-block text-sm transition-transform ${isThinking ? 'animate-pulse text-pink-400' : 'text-cyan-400'}`}>
            🧠
          </span>
          <span className="tracking-wider uppercase font-pixl text-[11px]">
            {isThinking 
              ? 'Thinking process...' 
              : (duration ? `Thought for ${duration}s` : 'Reasoning Process')}
          </span>
          {isThinking && (
            <span className="inline-flex items-center px-1.5 py-0.2 rounded-full text-[9px] font-code bg-pink-500/20 text-pink-300 animate-pulse border border-pink-500/40">
              Live
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5 text-slate-400 group-hover:text-cyan-300 transition-colors text-xs font-code">
          <span className="text-[10px] text-slate-500 group-hover:text-slate-400">
            {isOpen ? 'collapse' : 'expand'}
          </span>
          <ChevronDown
            className={`w-3.5 h-3.5 transition-transform duration-200 ${isOpen ? 'rotate-180 text-cyan-400' : 'text-slate-400'}`}
          />
        </div>
      </button>

      {isOpen && (
        <div className="px-3.5 py-3 border-t border-cyan-500/15 border-l-2 border-l-cyan-400 bg-black/25 text-xs text-slate-300 font-sans leading-relaxed max-h-80 overflow-y-auto scrollbar-thin select-text">
          <div className="whitespace-pre-wrap font-sans text-slate-300/90 text-xs sm:text-[13px] leading-relaxed">
            {reasoning || (isThinking ? 'Analyzing prompt and formulating solution...' : '')}
            {isThinking && (
              <span className="inline-block w-1.5 h-3.5 bg-cyan-400 ml-1 animate-pulse align-middle" />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function AgentArena({
  messages,
  inputPrompt,
  setInputPrompt,
  onSend,
  onClear,
  isExecuting,
  currentStep,
  activeTool,
  isAgentMode,
  modelName,
  sessionId
}) {
  const messagesEndRef = useRef(null);
  const textareaRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, currentStep]);

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (inputPrompt.trim() && !isExecuting) {
        onSend();
      }
    }
  };

  return (
    <div className="flex flex-col h-full w-full min-w-0 bg-[#080411]/90 rounded-2xl border border-pink-500/20 overflow-hidden shadow-[0_0_30px_rgba(0,0,0,0.6)]">
      
      {/* Arena Stream Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-[#0d071a] border-b border-pink-500/15">
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-red-500/80"></span>
            <span className="w-2.5 h-2.5 rounded-full bg-amber-500/80"></span>
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-500/80"></span>
          </div>
          <div className="h-3 w-px bg-white/10 mx-1"></div>
          <span className="font-code text-xs font-semibold tracking-wider text-slate-300 truncate">
            AGENT STREAM // <span className="text-pink-400 font-bold">{sessionId ? `SESSION: ${sessionId.slice(0, 16)}...` : 'READY'}</span>
          </span>
        </div>

        <div className="flex items-center gap-2">
          <span className="hidden sm:inline-flex items-center gap-1 px-2.5 py-0.5 rounded text-[11px] font-code bg-black/50 border border-slate-700/80 text-cyan-300">
            Model: <strong className="text-white font-pixl">{modelName || 'Auto'}</strong>
          </span>
          <span className={`px-2 py-0.5 rounded text-[10px] font-pixl font-bold tracking-wider ${
            isExecuting 
              ? 'bg-pink-500/20 border border-pink-500/50 text-pink-300 animate-pulse' 
              : 'bg-emerald-500/15 border border-emerald-500/40 text-emerald-400'
          }`}>
            {isExecuting ? 'PROCESSING' : 'READY'}
          </span>
        </div>
      </div>

      {/* Messages Stream */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden p-3 sm:p-5 space-y-4 sm:space-y-6 scrollbar-thin w-full min-w-0">
        {messages.length === 0 ? (
          /* Welcome Card with Generated Banner */
          <div className="relative rounded-2xl overflow-hidden border border-pink-500/30 glass-panel p-6 sm:p-8 max-w-3xl mx-auto my-auto shadow-2xl">
            {/* Background Graphic */}
            <div className="relative h-48 sm:h-64 -mx-6 sm:-mx-8 -mt-6 sm:-mt-8 mb-6 overflow-hidden rounded-t-2xl">
              <img 
                src="/kratos_banner.jpg" 
                alt="Kratos Agent Vice City" 
                className="w-full h-full object-cover object-center transform hover:scale-105 transition duration-700"
              />
              <div className="absolute inset-0 bg-gradient-to-t from-[#0d071a] via-[#0d071a]/40 to-transparent"></div>
              <div className="absolute bottom-4 left-6 sm:left-8">
                <span className="px-2.5 py-0.5 rounded text-[10px] font-rajdhani font-bold uppercase tracking-widest bg-pink-600/80 text-white shadow-md">
                  Autonomous Protocol
                </span>
                <h2 className="font-orbitron font-black text-2xl sm:text-3xl text-white tracking-wider mt-1 drop-shadow-md">
                  KRATOS <span className="text-vice-pink neon-text-pink">AGENT</span> VI
                </h2>
              </div>
            </div>

            <p className="text-sm text-slate-300 leading-relaxed font-sans mb-6">
              Welcome to the Kratos Agent web console. This platform integrates multi-step reasoning, autonomous tool execution loops, self-healing test verification, and global Cloudflare D1 persistence.
            </p>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div className="p-3.5 rounded-xl bg-black/40 border border-white/10 hover:border-pink-500/40 transition">
                <div className="flex items-center gap-2 mb-1.5 text-pink-400 font-rajdhani font-bold text-xs uppercase tracking-wider">
                  <Zap className="w-4 h-4" />
                  <span>Autonomous Loop</span>
                </div>
                <p className="text-xs text-slate-400">
                  Inspects files, executes shell commands, updates code, and verifies results automatically.
                </p>
              </div>

              <div className="p-3.5 rounded-xl bg-black/40 border border-white/10 hover:border-cyan-500/40 transition">
                <div className="flex items-center gap-2 mb-1.5 text-cyan-400 font-rajdhani font-bold text-xs uppercase tracking-wider">
                  <Terminal className="w-4 h-4" />
                  <span>Edge Socket Tunnel</span>
                </div>
                <p className="text-xs text-slate-400">
                  Direct raw TCP socket communication for seamless bypass of edge port limits.
                </p>
              </div>

              <div className="p-3.5 rounded-xl bg-black/40 border border-white/10 hover:border-amber-500/40 transition">
                <div className="flex items-center gap-2 mb-1.5 text-amber-400 font-rajdhani font-bold text-xs uppercase tracking-wider">
                  <Sparkles className="w-4 h-4" />
                  <span>Cloudflare D1</span>
                </div>
                <p className="text-xs text-slate-400">
                  All conversations, turns, and agentic trace events are permanently indexed.
                </p>
              </div>
            </div>

            <div className="mt-6 text-center text-xs font-rajdhani text-slate-400">
              Click a demo shortcut above or enter your instruction below to command Kratos Agent.
            </div>
          </div>
        ) : (
          messages.map((msg, index) => (
            <div 
              key={index}
              className={`flex gap-2.5 sm:gap-3.5 w-full min-w-0 ${msg.role === 'user' ? 'justify-end' : 'justify-start'} animate-fadeIn`}
            >
              {/* Agent Avatar */}
              {msg.role !== 'user' && (
                <div className="flex-shrink-0 mt-1">
                  <div className="relative">
                    <img 
                      src="/kratos_badge.png" 
                      alt="Kratos" 
                      className="w-8 h-8 sm:w-9 sm:h-9 rounded-xl object-cover border border-pink-500/40 shadow-[0_0_12px_rgba(255,0,127,0.3)]"
                    />
                  </div>
                </div>
              )}

              {/* Message Bubble */}
              <div className={`max-w-[92%] sm:max-w-[85%] min-w-0 overflow-hidden rounded-2xl p-3.5 sm:p-5 shadow-xl ${
                msg.role === 'user' 
                  ? 'bg-gradient-to-br from-[#1d0d33] to-[#120822] border border-pink-500/30 text-slate-100 rounded-tr-sm' 
                  : 'glass-card border-slate-700/60 text-slate-100 rounded-tl-sm'
              }`}>
                {/* Role Header */}
                <div className="flex items-center justify-between gap-2 mb-2 pb-1.5 border-b border-white/5 text-[11px] font-rajdhani font-bold tracking-wider">
                  <div className="flex items-center gap-1.5">
                    {msg.role === 'user' ? (
                      <>
                        <User className="w-3.5 h-3.5 text-pink-400" />
                        <span className="text-pink-300 font-pixl">COMMANDER // USER</span>
                      </>
                    ) : (
                      <>
                        <span className="text-cyan-400">⚔️</span>
                        <span className="text-cyan-300 font-pixl">KRATOS AGENT // AUTONOMOUS</span>
                      </>
                    )}
                  </div>
                  {msg.timestamp && (
                    <span className="text-[10px] font-code text-slate-500">{msg.timestamp}</span>
                  )}
                </div>

                {/* Reasoning Accordion */}
                {msg.role !== 'user' && (
                  <ReasoningAccordion
                    reasoning={msg.reasoning}
                    isThinking={msg.isThinking}
                    duration={msg.thinkingDuration}
                  />
                )}

                {/* Content */}
                <div className="prose prose-invert max-w-none text-sm leading-relaxed min-w-0 w-full overflow-x-auto break-words">
                  <MarkdownRenderer 
                    content={msg.content} 
                    isStreaming={isExecuting && index === messages.length - 1 && msg.role !== 'user' && !msg.isThinking} 
                  />
                </div>
              </div>

              {/* User Avatar */}
              {msg.role === 'user' && (
                <div className="flex-shrink-0 mt-1">
                  <div className="w-8 h-8 sm:w-9 sm:h-9 rounded-xl bg-gradient-to-tr from-[#ff007f] to-[#ff8c00] flex items-center justify-center text-white font-bold text-xs shadow-[0_0_12px_rgba(255,0,127,0.4)]">
                    CMD
                  </div>
                </div>
              )}
            </div>
          ))
        )}

        {/* Live Step Progression Feedback */}
        {isExecuting && currentStep && (
          <div className="flex items-start gap-3 p-3.5 rounded-xl bg-pink-950/25 border border-pink-500/40 text-xs font-code animate-pulse">
            <span className="text-pink-400 mt-0.5">⚡</span>
            <div>
              <div className="font-bold text-pink-300 tracking-wider font-pixl uppercase">
                {currentStep.tag || 'AGENT EXECUTION IN PROGRESS'}
              </div>
              <div className="text-slate-300 text-xs mt-0.5">
                {currentStep.label || 'Processing instructions...'}
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input Dock */}
      <div className="p-3 sm:p-4 bg-[#0a0515] border-t border-pink-500/20">
        <div className="relative flex items-end gap-2 p-2 rounded-xl bg-slate-950/80 border border-slate-700/80 focus-within:border-pink-500/60 focus-within:shadow-[0_0_20px_rgba(255,0,127,0.25)] transition duration-200">
          
          <div className="pb-2.5 pl-2 text-pink-400 font-code text-xs select-none flex items-center gap-1">
            <span className="text-pink-400 font-bold font-pixl">kratos</span>
            <span className="text-cyan-400">❯</span>
          </div>

          <textarea
            ref={textareaRef}
            value={inputPrompt}
            onChange={(e) => setInputPrompt(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Command Kratos Agent... (e.g. 'Audit project architecture and report status')"
            rows={1}
            disabled={isExecuting}
            className="flex-1 bg-transparent border-0 resize-none py-2 px-1 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-0 max-h-32 min-h-[40px] font-sans"
            style={{ height: 'auto', minHeight: '40px' }}
          />

          <div className="flex items-center gap-1.5 pb-1">
            {messages.length > 0 && (
              <button
                onClick={onClear}
                className="p-2 rounded-lg text-slate-400 hover:text-red-400 hover:bg-slate-800/60 transition"
                title="Clear current stream"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            )}

            <button
              onClick={onSend}
              disabled={!inputPrompt.trim() || isExecuting}
              className={`px-4 py-2 rounded-lg font-rajdhani font-bold text-xs tracking-wider flex items-center gap-1.5 transition duration-200 ${
                inputPrompt.trim() && !isExecuting
                  ? 'bg-gradient-to-r from-[#ff007f] to-[#ff8c00] text-white shadow-[0_0_15px_rgba(255,0,127,0.4)] hover:shadow-[0_0_20px_rgba(255,0,127,0.6)]'
                  : 'bg-slate-800 text-slate-500 cursor-not-allowed'
              }`}
            >
              <span>{isExecuting ? 'DISPATCHING...' : 'DISPATCH'}</span>
              <Send className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        {/* Input Footer Meta */}
        <div className="flex items-center justify-between px-2 pt-2 text-[11px] font-rajdhani text-slate-400">
          <div className="hidden xs:flex items-center gap-1">
            <span>Press <kbd className="px-1 py-0.5 rounded bg-slate-800 text-slate-300 text-[10px] font-code">Enter</kbd> to send</span>
            <span>·</span>
            <span><kbd className="px-1 py-0.5 rounded bg-slate-800 text-slate-300 text-[10px] font-code">Shift+Enter</kbd> for newline</span>
          </div>

          <div className="flex items-center gap-1.5 ml-auto">
            <span className="text-slate-500">MODE:</span>
            <span className={`font-bold tracking-wider ${isAgentMode ? 'text-pink-400' : 'text-cyan-400'}`}>
              {isAgentMode ? 'FULL AUTONOMOUS (AGENT)' : 'NORMAL CHAT (EDGE)'}
            </span>
          </div>
        </div>

      </div>

    </div>
  );
}
