import React, { useRef, useEffect, useState } from 'react';
import { Send, Trash2, Zap, Terminal, User, ChevronDown, Eye, Wrench, Square, LoaderCircle } from 'lucide-react';
import MarkdownRenderer from './MarkdownRenderer';
import ToolActivity from './ToolActivity';
import ContextMeter from './ContextMeter';
import { visibleMessageText } from '../speechDirectives';
import { isSavedToolFormatFailure, isToolFormatFailure } from '../chatRecovery';
import RecoveryNotice from './RecoveryNotice';
import KratosMark from './KratosMark';
import LiveControls from './LiveControls';
import LiveToolStatus from './LiveToolStatus';
import { liveStatusView } from '../liveStatusView';
import { groupedMessageTimeline, messageTimeline } from '../messageTimeline';
import { toolCardAnchor } from '../toolAnchors';

function ReasoningAccordion({ reasoning, isThinking, duration }) {
  const [manuallyOpen, setManuallyOpen] = useState(false);
  const isOpen = isThinking || manuallyOpen;

  if (!reasoning && !isThinking) return null;

  return (
    <div className="reasoning-box mb-3 rounded-xl border border-cyan-500/25 bg-[#0a1120]/70 overflow-hidden shadow-[0_2px_12px_rgba(0,0,0,0.3)] transition-all">
      <button
        type="button"
        onClick={() => setManuallyOpen(!isOpen)}
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
  runningTools = [],
  inputPrompt,
  setInputPrompt,
  onSend,
  onStop,
  onRetry,
  isStopping,
  isWorkspaceStarting,
  executionError,
  recoveryNotice,
  onDismissRecoveryNotice,
  onOpenActivity,
  onClear,
  isExecuting,
  currentStep,
  activeTool,
  isAgentMode,
  modelName,
  modelModality,
  contextUsage,
  onCompactContext,
  isCompacting,
  contextNotice,
  contextError,
  onOpenModelPicker,
  sessionId,
  onVisionMode,
  liveStatus,
  liveControlError,
  liveControlPending,
  onLiveControl,
  taskDetails
}) {
  const messagesEndRef = useRef(null);
  const messagesContainerRef = useRef(null);
  const textareaRef = useRef(null);
  const followStreamRef = useRef(true);
  const [visionError, setVisionError] = useState('');
  const activeVisionMode = liveStatusView(liveStatus).visionMode;
  const captureError = visionError || liveStatus?.errors?.camera || liveStatus?.errors?.screen || '';

  const changeVisionMode = async (mode) => {
    setVisionError('');
    try {
      await onVisionMode?.(mode);
    } catch (error) {
      setVisionError(error.message || 'Could not change vision mode.');
    }
  };

  useEffect(() => { followStreamRef.current = true; }, [sessionId]);

  useEffect(() => {
    if (messages.length > 0 && messagesContainerRef.current && followStreamRef.current) {
      messagesContainerRef.current.scrollTo({
        top: messagesContainerRef.current.scrollHeight,
        behavior: 'auto'
      });
    }
  }, [messages, currentStep]);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = 'auto';
    textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`;
  }, [inputPrompt]);

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (inputPrompt.trim() && !isExecuting && !isWorkspaceStarting && !isCompacting) {
        onSend();
      }
    }
  };

  return (
    <div className="chat-panel flex flex-col h-full w-full min-w-0 min-h-0 bg-[#080411]/90 rounded-2xl border border-pink-500/20 overflow-hidden shadow-[0_0_30px_rgba(0,0,0,0.6)]">

      {/* Arena Stream Header */}
      <div className="chat-panel-header flex-shrink-0 flex items-center justify-between px-4 py-3 bg-[#0d071a] border-b border-pink-500/15">
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-red-500/80"></span>
            <span className="w-2.5 h-2.5 rounded-full bg-amber-500/80"></span>
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-500/80"></span>
          </div>
          <div className="h-3 w-px bg-white/10 mx-1"></div>
          <span className="font-code text-xs font-semibold tracking-wider text-slate-300 truncate">
            Conversation <span className="conversation-session">{sessionId ? `· ${sessionId.slice(-8)}` : ''}</span>
          </span>
        </div>

        <div className="flex items-center gap-2">
          {activeTool && (
            <span className="hidden md:inline-flex items-center gap-1.5 rounded-md border border-cyan-400/25 bg-cyan-400/5 px-2 py-1 text-[10px] font-code text-cyan-200" title="Tool currently running">
              <Wrench className="h-3 w-3" />
              {typeof activeTool === 'string' ? activeTool : activeTool.name || activeTool.tool || 'TOOL RUNNING'}
            </span>
          )}
          <button type="button" className="chat-model-picker" onClick={onOpenModelPicker} disabled={isExecuting}
            aria-label={`Change model. Current model: ${modelName || 'Auto'}`} aria-haspopup="dialog"
            title={isExecuting ? 'Finish or stop the current task to change models' : 'Change model'}>
            <span>Model:</span><strong>{modelName || 'Auto'}</strong><span className="model-modality-label">{modelModality || 'Capabilities not reported'}</span><ChevronDown size={14} />
          </button>
          <span className={`px-2 py-0.5 rounded text-[10px] font-pixl font-bold tracking-wider ${
            isExecuting
              ? 'bg-pink-500/20 border border-pink-500/50 text-pink-300 animate-pulse'
              : 'bg-emerald-500/15 border border-emerald-500/40 text-emerald-400'
          }`}>
            {isWorkspaceStarting ? 'STARTING' : (isStopping ? 'STOPPING' : (isExecuting ? 'PROCESSING' : 'READY'))}
          </span>
        </div>
      </div>

      <ContextMeter context={contextUsage} isExecuting={isExecuting} isCompacting={isCompacting}
        onCompact={onCompactContext} notice={contextNotice} error={contextError} />

      {taskDetails}

      {/* Messages Stream */}
      <div
        ref={messagesContainerRef}
        onScroll={event => { const element = event.currentTarget; followStreamRef.current = element.scrollHeight - element.scrollTop - element.clientHeight < 96; }}
        className="conversation-stream flex-1 min-h-0 overflow-y-auto overflow-x-hidden p-3 sm:p-5 space-y-4 sm:space-y-6 scrollbar-thin w-full min-w-0"
      >
        {messages.length === 0 ? (
          <div className="workspace-welcome">
            <div className="welcome-symbol"><KratosMark size={54} title="" /></div>
            <span className="welcome-eyebrow">CREATE · EXPLORE · GET THINGS DONE</span>
            <h1>What are we working on?</h1>
            <p>A place to think, build, and move your work forward.</p>
            <div className="welcome-suggestions">
              {[
                [Terminal, 'Explore a project', 'Review the workspace and explain its architecture.'],
                [Wrench, 'Fix an issue', 'Help me investigate a problem in this project.'],
                [Zap, 'Plan a task', 'Help me make a practical implementation plan.'],
              ].map(([Icon, title, prompt]) => (
                <button key={title} onClick={() => { setInputPrompt(prompt); textareaRef.current?.focus(); }}>
                  <Icon size={19} /><strong>{title}</strong><span>Start a conversation →</span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((msg, index) => (
            <div
              key={index}
              className={`chat-turn flex gap-2.5 sm:gap-3.5 w-full min-w-0 ${msg.role === 'user' ? 'user-turn justify-end' : 'assistant-turn justify-start'} animate-fadeIn`}
            >
              {/* Agent Avatar */}
              {msg.role !== 'user' && (
                <div className="assistant-avatar flex-shrink-0 mt-1"><KratosMark size={30} /></div>
              )}

              {/* Message Bubble */}
              <div className={`chat-message max-w-[92%] sm:max-w-[85%] min-w-0 overflow-hidden rounded-2xl p-3.5 sm:p-5 shadow-xl ${
                msg.role === 'user'
                  ? 'user-message text-slate-100'
                  : 'assistant-message text-slate-100'
              }`}>
                {/* Role Header */}
                <div className="flex items-center justify-between gap-2 mb-2 pb-1.5 border-b border-white/5 text-[11px] font-rajdhani font-bold tracking-wider">
                  <div className="flex items-center gap-1.5">
                    {msg.role === 'user' ? (
                      <>
                        <User className="w-3.5 h-3.5 text-pink-400" />
                        <span className="text-pink-300 font-pixl">You</span>
                      </>
                    ) : (
                      <>
                        <span className="text-cyan-300 font-pixl">Kratos</span>
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
                <div className="message-timeline">
                  {(msg.role === 'user' ? [{ id: 'user-text', type: 'text', content: visibleMessageText(msg) }] : groupedMessageTimeline(messageTimeline(msg))).map((block, blockIndex, blocks) => block.type === 'tool-group'
                    ? <ToolActivity key={block.id} activities={block.blocks.map(call => call.activity)} anchors={Object.fromEntries(block.blocks.map(call => [call.activity.id, toolCardAnchor(index, call.activity.id)]))} />
                    : !isSavedToolFormatFailure(msg) && <div className="prose prose-invert max-w-none text-sm leading-relaxed min-w-0 w-full overflow-x-auto break-words" key={block.id}>
                      <MarkdownRenderer content={block.content}
                        isStreaming={isExecuting && index === messages.length - 1 && blockIndex === blocks.length - 1 && msg.role !== 'user' && !msg.isThinking} />
                    </div>)}
                </div>
                {isSavedToolFormatFailure(msg) && <p className="recovery-history">
                  Earlier attempt ended before completion. <button type="button" onClick={onOpenActivity}>View Activity</button>
                </p>}
                {!isSavedToolFormatFailure(msg) && ['cancelled', 'failed', 'paused', 'interrupted'].includes(msg.status) && (
                  <p className={`turn-status turn-${msg.status}`} role="status">
                    {msg.status === 'cancelled' ? 'Stopped by you. Existing changes were kept.' : msg.status === 'failed' ? 'Needs attention. Completed work is saved.' : msg.status === 'paused' ? 'This task is paused.' : 'Response interrupted; completion could not be confirmed.'}
                    {msg.status === 'failed' && index === messages.length - 1 && <button type="button" className="context-compact-button ml-2" disabled={isExecuting} onClick={onRetry}>Retry task</button>}
                  </p>
                )}
              </div>

              {/* User Avatar */}
            </div>
          ))
        )}

        {/* Live Step Progression Feedback */}
        {isExecuting && currentStep && (
          <div className="chat-progress flex items-start gap-3 text-xs font-code" role="status">
            <LoaderCircle className="animate-spin" size={14} />
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
      <div className="composer-dock flex-shrink-0 p-3 sm:p-4 bg-[#0a0515] border-t border-pink-500/20">
        <div className="composer-toolbar">
        <div className="vision-controls flex flex-wrap items-center gap-1.5 mb-2 px-1" aria-label="Vision controls">
          <span className="inline-flex items-center gap-1.5 mr-1 text-[11px] font-code text-cyan-300">
            <Eye className="w-3.5 h-3.5" />
            <code>/vision</code>
          </span>
          {[
            ['camera', 'CAM'],
            ['screen', 'SCREEN'],
            ['both', 'BOTH'],
            ['none', 'OFF'],
          ].map(([mode, label]) => (
            <button
              key={mode}
              type="button"
              onClick={() => changeVisionMode(mode)}
              disabled={isExecuting || Boolean(liveControlPending)}
              aria-pressed={activeVisionMode === mode}
              title={`/vision ${mode === 'none' ? 'off' : mode}`}
              className={`rounded-md border px-2 py-1 text-[9px] font-code tracking-wider transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 disabled:opacity-50 ${
                activeVisionMode === mode
                  ? 'border-cyan-400/60 bg-cyan-400/15 text-cyan-200 shadow-[0_0_10px_rgba(0,243,255,0.12)]'
                  : 'border-white/10 bg-black/20 text-slate-400 hover:border-cyan-400/40 hover:text-cyan-200'
              }`}
            >
              {liveControlPending?.action === 'set_vision_mode' && liveControlPending.value === mode ? <LoaderCircle size={12} className="animate-spin" /> : label}
            </button>
          ))}
          <small className="vision-capture-status" role="status">{liveControlPending?.action === 'set_vision_mode' ? 'Updating capture…' : activeVisionMode === 'none' ? 'Capture off' : `${activeVisionMode === 'both' ? 'Camera + screen' : activeVisionMode === 'camera' ? 'Camera' : 'Screen'} capture active`}</small>
        </div>
        <LiveControls status={liveStatus} error={liveControlError} pending={liveControlPending} onControl={onLiveControl} />
        </div>
        <LiveToolStatus tools={runningTools} />
        {captureError && captureError !== liveControlError && <p role="status" className="mb-2 px-1 text-xs text-rose-300">{captureError}</p>}
        {executionError && !isToolFormatFailure(executionError) && <p role="status" className="execution-error">{executionError}</p>}
        <RecoveryNotice notice={recoveryNotice} onDismiss={onDismissRecoveryNotice} />
        {isStopping && <p role="status" className="execution-notice">Stopping… waiting for the running operation to exit.</p>}
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
            placeholder="Describe what you want to do…" aria-label="Task instruction"
            rows={1}
            disabled={isExecuting}
            className="flex-1 bg-transparent border-0 resize-none py-2 px-1 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-0 max-h-32 min-h-[40px] font-sans"
            style={{ height: 'auto', minHeight: '40px' }}
          />

          <div className="flex items-center gap-1.5 pb-1">
            {messages.length > 0 && (
              <button
                onClick={onClear}
                disabled={isExecuting}
                className="p-2 rounded-lg text-slate-400 hover:text-red-400 hover:bg-slate-800/60 transition"
                title="Clear current stream"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            )}

            {isExecuting ? <button
              type="button"
              onClick={onStop}
              disabled={isStopping}
              className="stop-execution"
              aria-label={isStopping ? 'Stopping task' : 'Stop task'}
              title="Stop the current task. Changes already made are kept."
            >
              {isStopping ? <LoaderCircle className="animate-spin" size={15} /> : <Square size={14} fill="currentColor" />}
              <span>{isStopping ? 'Stopping…' : 'Stop'}</span>
            </button> : <button
              onClick={onSend}
              disabled={!inputPrompt.trim() || isExecuting || isWorkspaceStarting || isCompacting}
              className={`px-4 py-2 rounded-lg font-rajdhani font-bold text-xs tracking-wider flex items-center gap-1.5 transition duration-200 ${
                inputPrompt.trim() && !isExecuting && !isWorkspaceStarting && !isCompacting
                  ? 'bg-gradient-to-r from-[#ff007f] to-[#ff8c00] text-white shadow-[0_0_15px_rgba(255,0,127,0.4)] hover:shadow-[0_0_20px_rgba(255,0,127,0.6)]'
                  : 'bg-slate-800 text-slate-500 cursor-not-allowed'
              }`}
            >
              <span>Send</span>
              <Send className="w-3.5 h-3.5" />
            </button>}
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
              {isAgentMode ? 'Agent mode' : 'Direct chat'}
            </span>
          </div>
        </div>

      </div>

    </div>
  );
}
