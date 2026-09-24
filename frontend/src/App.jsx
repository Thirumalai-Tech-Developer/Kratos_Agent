import React, { useState, useEffect } from 'react';
import Navbar from './components/Navbar';
import RecruiterStrip from './components/RecruiterStrip';
import AgentArena from './components/AgentArena';
import AgentHud from './components/AgentHud';
import SessionsExplorer from './components/SessionsExplorer';
import TraceReplay from './components/TraceReplay';
import SqlPlayground from './components/SqlPlayground';
import { AgentAuthModal, TechSpecsModal, PayloadModal } from './components/Modals';
import { Gamepad2, MessageSquare, Zap, Database } from 'lucide-react';

export default function App() {
  // Navigation
  const [activeTab, setActiveTab] = useState('arena');
  const [isHudOpen, setIsHudOpen] = useState(false);

  // Core Data State
  const [stats, setStats] = useState(null);
  const [telemetry, setTelemetry] = useState(null);
  const [tools, setTools] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [activeSessionData, setActiveSessionData] = useState(null);
  const [events, setEvents] = useState([]);
  const [sqlResults, setSqlResults] = useState([]);
  const [sqlLoading, setSqlLoading] = useState(false);
  const [sqlError, setSqlError] = useState(null);
  const [liveStatus, setLiveStatus] = useState(null);
  const [liveControlError, setLiveControlError] = useState(null);

  // Chat & Execution State
  const [messages, setMessages] = useState([]);
  const [inputPrompt, setInputPrompt] = useState('');
  const [isExecuting, setIsExecuting] = useState(false);
  const [currentStep, setCurrentStep] = useState(null);
  const [activeTool, setActiveTool] = useState(null);
  const [isAgentMode, setIsAgentMode] = useState(true);
  const [agentPassword, setAgentPassword] = useState('kratos');

  // Modals
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [authError, setAuthError] = useState(null);
  const [techSpecsOpen, setTechSpecsOpen] = useState(false);
  const [payloadModalOpen, setPayloadModalOpen] = useState(false);
  const [selectedEvent, setSelectedEvent] = useState(null);

  const fetchStats = async () => {
    try {
      const res = await fetch('/api/stats');
      if (res.ok) setStats(await res.json());
    } catch {}
  };

  const fetchTelemetry = async () => {
    try {
      const res = await fetch('/api/telemetry');
      if (res.ok) setTelemetry(await res.json());
    } catch {}
  };

  const fetchTools = async () => {
    try {
      const res = await fetch('/api/tools');
      if (res.ok) setTools(await res.json());
    } catch {}
  };

  const fetchSessions = async () => {
    try {
      const res = await fetch('/api/sessions');
      if (res.ok) {
        const data = await res.json();
        setSessions(data || []);
      }
    } catch {}
  };

  const fetchSessionDetail = async (id) => {
    if (!id) return;
    try {
      const res = await fetch(`/api/sessions/${id}`);
      if (res.ok) {
        const data = await res.json();
        setActiveSessionData(data);
      }
    } catch {}
  };

  const fetchEvents = async (sId = null) => {
    try {
      const url = sId ? `/api/events/${sId}` : '/api/events';
      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        setEvents(data || []);
      }
    } catch {}
  };

  const fetchLiveStatus = async () => {
    try {
      const res = await fetch('/api/live/status');
      if (res.ok) {
        setLiveStatus(await res.json());
      }
    } catch {}
  };

  const refreshAll = async () => {
    await Promise.all([
      fetchStats(),
      fetchTelemetry(),
      fetchTools(),
      fetchSessions(),
      fetchEvents(),
      fetchLiveStatus()
    ]);
  };

  // Initial Load & polling
  useEffect(() => {
    const initialRefresh = setTimeout(refreshAll, 0);
    const interval = setInterval(fetchLiveStatus, 3000);
    return () => {
      clearTimeout(initialRefresh);
      clearInterval(interval);
    };
  }, []);

  const handleLiveControl = async (action, value = null) => {
    try {
      const res = await fetch('/api/live/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, value }),
      });
      if (res.ok) {
        setLiveStatus(await res.json());
        setLiveControlError(null);
      } else {
        const data = await res.json().catch(() => ({}));
        setLiveControlError(data.error || `Live control failed (${res.status})`);
      }
    } catch (error) {
      setLiveControlError(error.message || 'Could not reach the Live runtime.');
    }
  };

  const setVisionMode = async (mode) => {
    const response = await fetch('/api/live/control', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'set_vision_mode', value: mode }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `Vision mode request failed (${response.status})`);
    setLiveStatus(data);
    setLiveControlError(null);
    return data.video_mode || mode;
  };

  // Toggle between autonomous task execution and direct chat.
  const handleToggleAgentMode = () => {
    setIsAgentMode(prev => !prev);
  };

  const handleAuthenticate = async (pwd) => {
    setIsAgentMode(true);
    setAgentPassword(pwd || 'kratos');
    setAuthModalOpen(false);
    setAuthError(null);
  };

function parseThinkTags(rawContent, currentReasoning = '') {
  let reasoning = currentReasoning || '';
  let content = rawContent || '';

  if (content.includes('<think>')) {
    const startIdx = content.indexOf('<think>') + 7;
    const endIdx = content.indexOf('</think>');
    if (endIdx !== -1) {
      const extracted = content.substring(startIdx, endIdx).trim();
      reasoning = (reasoning ? reasoning + '\n' : '') + extracted;
      content = (content.substring(0, startIdx - 7) + content.substring(endIdx + 8)).trim();
      return { reasoning, content, isThinking: false };
    } else {
      const extracted = content.substring(startIdx);
      reasoning = (reasoning ? reasoning + '\n' : '') + extracted;
      content = content.substring(0, startIdx - 7);
      return { reasoning, content, isThinking: true };
    }
  }

  return { reasoning, content, isThinking: false };
}

  // Dispatch Chat Prompt
  const handleSendPrompt = async (customPrompt = null) => {
    const text = (customPrompt || inputPrompt).trim();
    if (!text || isExecuting) return;

    const visionCommand = text.match(/^\/vision(?:\s+(.*))?$/i);
    if (visionCommand) {
      const modes = ['camera', 'screen', 'both', 'none'];
      const requestedMode = visionCommand[1]?.toLowerCase().trim();
      const nextMode = requestedMode || modes[(modes.indexOf(liveStatus?.video_mode || 'camera') + 1) % modes.length];
      const userMessage = { role: 'user', content: text, timestamp: new Date().toLocaleTimeString() };
      setInputPrompt('');
      setMessages((prev) => [...prev, userMessage, {
        role: 'agent',
        content: 'Updating vision source…',
        timestamp: new Date().toLocaleTimeString(),
      }]);
      if (requestedMode && ![...modes, 'off'].includes(requestedMode)) {
        setMessages((prev) => {
          const updated = [...prev];
          const lastIndex = updated.length - 1;
          updated[lastIndex] = { ...updated[lastIndex], content: 'Usage: `/vision camera`, `/vision screen`, `/vision both`, or `/vision off`.' };
          return updated;
        });
        return;
      }
      try {
        const activeMode = await setVisionMode(nextMode === 'off' ? 'none' : nextMode);
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last?.role === 'agent') {
            updated[updated.length - 1] = {
              ...last,
              content: `Vision source ${activeMode === 'none' || activeMode === 'off' ? 'disabled' : `set to **${activeMode}**`}.`,
            };
          }
          return updated;
        });
      } catch (error) {
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last?.role === 'agent') {
            updated[updated.length - 1] = { ...last, content: `Could not change vision mode: ${error.message}` };
          }
          return updated;
        });
      }
      return;
    }

    setInputPrompt('');
    setIsExecuting(true);
    setCurrentStep({ tag: 'INITIALIZING', label: 'Connecting to Kratos Edge Worker...' });

    // Append user message
    const userMsg = {
      role: 'user',
      content: text,
      timestamp: new Date().toLocaleTimeString()
    };
    setMessages((prev) => [...prev, userMsg]);

    // Prepare agent message placeholder
    const agentMsgIndex = messages.length + 1;
    const initialAgentMsg = {
      role: 'agent',
      content: '',
      reasoning: '',
      isThinking: false,
      thinkingDuration: 0,
      timestamp: new Date().toLocaleTimeString()
    };
    setMessages((prev) => [...prev, initialAgentMsg]);

    let rawContent = '';
    let accumulatedReasoning = '';
    let isActivelyThinking = false;
    let thinkStartTime = Date.now();
    let thinkingDuration = 0;

    try {
      const payload = {
        session_id: activeSessionId,
        prompt: text,
        message: text,
        query: text,
        mode: isAgentMode ? 'agent' : 'chat',
        agent_mode: isAgentMode,
        is_agent_mode: isAgentMode,
        agent_password: agentPassword
      };

      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        const errText = await res.text().catch(() => '');
        rawContent = `⚠️ **Error HTTP ${res.status}**: ${errText || 'Edge server error'}`;
        setMessages((prev) => {
          const updated = [...prev];
          updated[agentMsgIndex] = { ...updated[agentMsgIndex], content: rawContent };
          return updated;
        });
        setIsExecuting(false);
        setCurrentStep(null);
        return;
      }

      // Check content-type for SSE stream
      const contentType = res.headers.get('content-type') || '';
      if (contentType.includes('text/event-stream')) {
        const reader = res.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop(); // keep remainder

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed || trimmed.startsWith(':')) continue;

            if (trimmed.startsWith('data:')) {
              try {
                const data = JSON.parse(trimmed.slice(5).trim());

                if (data.session_id && !activeSessionId) {
                  setActiveSessionId(data.session_id);
                }

                // Handle reasoning stream events
                if (data.type === 'reasoning' || data.reasoning_token || (data.step === 'reasoning' && data.reasoning)) {
                  const rChunk = data.reasoning_token || data.token || data.reasoning || '';
                  if (rChunk) {
                    accumulatedReasoning += rChunk;
                    isActivelyThinking = true;
                    thinkingDuration = Math.max(1, Math.round((Date.now() - thinkStartTime) / 1000));
                    setMessages((prev) => {
                      const updated = [...prev];
                      updated[agentMsgIndex] = {
                        ...updated[agentMsgIndex],
                        reasoning: accumulatedReasoning,
                        isThinking: true,
                        thinkingDuration
                      };
                      return updated;
                    });
                  }
                }

                if (data.token) {
                  rawContent += data.token;
                  const parsed = parseThinkTags(rawContent, accumulatedReasoning);
                  if (parsed.isThinking) {
                    isActivelyThinking = true;
                    thinkingDuration = Math.max(1, Math.round((Date.now() - thinkStartTime) / 1000));
                  } else if (isActivelyThinking && parsed.content) {
                    isActivelyThinking = false;
                    thinkingDuration = Math.max(1, Math.round((Date.now() - thinkStartTime) / 1000));
                  }

                  setMessages((prev) => {
                    const updated = [...prev];
                    updated[agentMsgIndex] = {
                      ...updated[agentMsgIndex],
                      content: parsed.content,
                      reasoning: parsed.reasoning || accumulatedReasoning,
                      isThinking: isActivelyThinking,
                      thinkingDuration
                    };
                    return updated;
                  });
                } else if (data.result || data.reply || data.response || data.content) {
                  const finalTxt = data.result || data.reply || data.response || data.content;
                  if (finalTxt && (!rawContent || finalTxt.length > rawContent.length)) {
                    rawContent = finalTxt;
                  }
                  const parsed = parseThinkTags(rawContent, accumulatedReasoning);
                  setMessages((prev) => {
                    const updated = [...prev];
                    updated[agentMsgIndex] = {
                      ...updated[agentMsgIndex],
                      content: parsed.content,
                      reasoning: parsed.reasoning || accumulatedReasoning,
                      isThinking: false,
                      thinkingDuration: thinkingDuration || (accumulatedReasoning ? Math.max(1, Math.round((Date.now() - thinkStartTime) / 1000)) : 0)
                    };
                    return updated;
                  });
                }

                if (data.step) {
                  const stepObj = typeof data.step === 'object' && data.step !== null
                    ? data.step
                    : { tag: String(data.step).toUpperCase(), label: data.label || String(data.step) };
                  setCurrentStep(stepObj);
                }

                if (data.tool_call) {
                  setActiveTool(data.tool_call);
                }

                if (data.tool_result) {
                  setActiveTool(null);
                }
              } catch {}
            }
          }
        }

        // Stream completed cleanly: finalize parse and lock duration
        const parsedFinal = parseThinkTags(rawContent, accumulatedReasoning);
        setMessages((prev) => {
          const updated = [...prev];
          if (updated[agentMsgIndex]) {
            updated[agentMsgIndex] = {
              ...updated[agentMsgIndex],
              content: parsedFinal.content || rawContent,
              reasoning: parsedFinal.reasoning || accumulatedReasoning,
              isThinking: false,
              thinkingDuration: thinkingDuration || (accumulatedReasoning ? Math.max(1, Math.round((Date.now() - thinkStartTime) / 1000)) : 0)
            };
          }
          return updated;
        });
      } else {
        // Standard JSON response
        const data = await res.json().catch(() => ({}));
        rawContent = data.result || data.reply || data.response || data.content || JSON.stringify(data);
        if (data.session_id) setActiveSessionId(data.session_id);
        const parsed = parseThinkTags(rawContent, accumulatedReasoning);
        setMessages((prev) => {
          const updated = [...prev];
          updated[agentMsgIndex] = {
            ...updated[agentMsgIndex],
            content: parsed.content,
            reasoning: parsed.reasoning || accumulatedReasoning,
            isThinking: false,
            thinkingDuration: 0
          };
          return updated;
        });
      }
    } catch (err) {
      rawContent = `⚠️ **Connection Error**: ${err.message || String(err)}`;
      setMessages((prev) => {
        const updated = [...prev];
        updated[agentMsgIndex] = { ...updated[agentMsgIndex], content: rawContent };
        return updated;
      });
    } finally {
      setIsExecuting(false);
      setCurrentStep(null);
      setActiveTool(null);
      refreshAll();
    }
  };

  // Resume Session in Arena
  const handleResumeSession = async (sessionId) => {
    setActiveSessionId(sessionId);
    setActiveTab('arena');
    try {
      const res = await fetch(`/api/sessions/${sessionId}`);
      if (res.ok) {
        const data = await res.json();
        setActiveSessionData(data);
        const turnsList = data.turns || [];
        if (turnsList.length > 0) {
          const restoredMessages = [];
          turnsList.forEach((t) => {
            const userContent = t.user_query || t.user || t.prompt || t.query || '';
            const rawAgentContent = t.agent_reply || t.agent || t.reply || t.response || t.content || '';
            const parsed = parseThinkTags(rawAgentContent);

            let timeStr = '';
            if (t.timestamp) {
              try {
                timeStr = new Date(t.timestamp).toLocaleTimeString();
              } catch {
                timeStr = String(t.timestamp);
              }
            }

            if (userContent) {
              restoredMessages.push({
                role: 'user',
                content: userContent,
                timestamp: timeStr
              });
            }

            if (rawAgentContent) {
              restoredMessages.push({
                role: 'agent',
                content: parsed.content || rawAgentContent,
                reasoning: parsed.reasoning || '',
                isThinking: false,
                thinkingDuration: 0,
                timestamp: timeStr
              });
            }
          });
          setMessages(restoredMessages);
        }
      }
    } catch {}
  };

  // Delete Session
  const handleDeleteSession = async (sessionId) => {
    if (!confirm('Are you sure you want to delete this session from Cloudflare D1?')) return;
    try {
      const res = await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
      if (res.ok) {
        if (activeSessionId === sessionId) {
          setActiveSessionId(null);
          setActiveSessionData(null);
          setMessages([]);
        }
        fetchSessions();
      }
    } catch {}
  };

  // SQL Execution
  const handleExecuteSql = async (query) => {
    setSqlLoading(true);
    setSqlError(null);
    try {
      const res = await fetch('/api/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sql: query })
      });
      const data = await res.json();
      if (res.ok) {
        setSqlResults(data.results || data.data || []);
      } else {
        setSqlError(data.error || 'SQL query failed');
      }
    } catch (err) {
      setSqlError(err.message || 'Network error executing SQL');
    } finally {
      setSqlLoading(false);
    }
  };

  return (
    <div className="h-screen w-screen bg-[#07030e] text-slate-100 flex flex-col selection:bg-pink-600 selection:text-white cyber-grid-bg overflow-hidden">
      
      {/* Top Navbar */}
      <div className="flex-shrink-0 z-40">
        <Navbar
          stats={stats}
          isAgentMode={isAgentMode}
          onToggleAgentMode={handleToggleAgentMode}
          onRefresh={refreshAll}
          onNewSession={() => {
            setActiveSessionId(null);
            setActiveSessionData(null);
            setMessages([]);
            setActiveTab('arena');
          }}
          onOpenTechSpecs={() => setTechSpecsOpen(true)}
          isHudOpen={isHudOpen}
          onToggleHud={() => setIsHudOpen(!isHudOpen)}
          onSelectTab={(tab) => setActiveTab(tab)}
        />
      </div>

      {/* Navigation Tabs Bar */}
      <div className="w-full flex-shrink-0 bg-[#0b0616] border-b border-pink-500/15 px-4 sm:px-6 lg:px-8">
        <div className="max-w-[1600px] mx-auto flex items-center justify-between overflow-x-auto scrollbar-none">
          <div className="flex items-center gap-1 sm:gap-2 py-2">
            <button
              onClick={() => setActiveTab('arena')}
              className={`px-3.5 py-2 rounded-xl text-xs font-pixl font-bold flex items-center gap-2 transition duration-200 whitespace-nowrap ${
                activeTab === 'arena'
                  ? 'bg-gradient-to-r from-pink-600/30 to-slate-900 border border-pink-500 text-white shadow-[0_0_15px_rgba(255,0,127,0.3)]'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-white/5'
              }`}
            >
              <Gamepad2 className="w-4 h-4 text-pink-400" />
              <span>AGENT ARENA & LIVE HUD</span>
              <span className="px-1.5 py-0.2 text-[9px] rounded-full bg-pink-500 text-white font-pixl animate-pulse">
                LIVE
              </span>
            </button>

            <button
              onClick={() => { setActiveTab('sessions'); fetchSessions(); }}
              className={`px-3.5 py-2 rounded-xl text-xs font-pixl font-bold flex items-center gap-2 transition duration-200 whitespace-nowrap ${
                activeTab === 'sessions'
                  ? 'bg-gradient-to-r from-cyan-600/30 to-slate-900 border border-cyan-500 text-white shadow-[0_0_15px_rgba(0,243,255,0.3)]'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-white/5'
              }`}
            >
              <MessageSquare className="w-4 h-4 text-cyan-400" />
              <span>D1 SESSIONS & TURNS</span>
              <span className="px-1.5 py-0.2 text-[9px] rounded-full bg-slate-800 text-cyan-300 font-pixl">
                {stats?.sessions_count ?? sessions?.length ?? 0}
              </span>
            </button>

            <button
              onClick={() => { setActiveTab('traces'); fetchEvents(); }}
              className={`px-3.5 py-2 rounded-xl text-xs font-pixl font-bold flex items-center gap-2 transition duration-200 whitespace-nowrap ${
                activeTab === 'traces'
                  ? 'bg-gradient-to-r from-amber-600/30 to-slate-900 border border-amber-500 text-white shadow-[0_0_15px_rgba(255,140,0,0.3)]'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-white/5'
              }`}
            >
              <Zap className="w-4 h-4 text-amber-400" />
              <span>AGENTIC TRACE REPLAY</span>
              <span className="px-1.5 py-0.2 text-[9px] rounded-full bg-slate-800 text-amber-300 font-pixl">
                {events?.length ?? 0}
              </span>
            </button>

            <button
              onClick={() => setActiveTab('sql')}
              className={`px-3.5 py-2 rounded-xl text-xs font-pixl font-bold flex items-center gap-2 transition duration-200 whitespace-nowrap ${
                activeTab === 'sql'
                  ? 'bg-gradient-to-r from-purple-600/30 to-slate-900 border border-purple-500 text-white shadow-[0_0_15px_rgba(168,85,247,0.3)]'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-white/5'
              }`}
            >
              <Database className="w-4 h-4 text-purple-400" />
              <span>D1 SQL PLAYGROUND</span>
            </button>
          </div>

          {/* Live Multimodal Perception Bar */}
          <div className="flex items-center gap-1.5 sm:gap-2.5 py-1.5 px-3 rounded-xl bg-slate-900/80 border border-white/10 text-xs font-rajdhani whitespace-nowrap">
            <div className="flex items-center gap-1.5">
              <span className="relative flex h-2 w-2">
                <span className={`animate-ping absolute inline-flex h-full w-full rounded-full ${liveStatus?.gemini_connected ? 'bg-emerald-400' : 'bg-amber-400'} opacity-75`}></span>
                <span className={`relative inline-flex rounded-full h-2 w-2 ${liveStatus?.gemini_connected ? 'bg-emerald-500' : 'bg-amber-500'}`}></span>
              </span>
              <span title={liveControlError || liveStatus?.errors?.gemini || liveStatus?.last_error || 'Gemini Live status'} className={`font-pixl font-bold text-[10px] ${liveStatus?.gemini_connected ? 'text-emerald-400' : 'text-amber-400'}`}>
                {liveStatus?.gemini_connected ? 'LIVE' : 'LIVE IDLE'}
              </span>
            </div>

            <div className="h-3 w-px bg-white/10"></div>

            <button
              onClick={() => handleLiveControl('toggle_mute')}
              title={liveControlError || liveStatus?.errors?.microphone || (liveStatus?.muted ? 'Microphone muted. Click to unmute.' : 'Microphone is controlled by Gemini Live. Click to mute or unmute.')}
              aria-label={liveStatus?.muted ? 'Unmute microphone' : 'Mute microphone'}
              className={`px-2 py-0.5 rounded text-[10px] font-pixl flex items-center gap-1 transition ${
                liveStatus?.muted
                  ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                  : (liveStatus?.microphone_active ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30' : 'bg-white/5 text-slate-400')
              }`}
            >
              <span>🎤</span>
              <span>{liveStatus?.muted ? 'MUTED' : (liveStatus?.microphone_active ? (liveStatus?.gemini_connected ? 'MIC LIVE' : 'MIC LOCAL') : 'MIC OFF')}</span>
            </button>
            <span className={`text-[9px] font-pixl ${liveStatus?.speaker_active ? 'text-emerald-300' : 'text-slate-500'}`} title={liveStatus?.errors?.speaker || 'Gemini speech playback'}>
              OUT {liveStatus?.speaker_active ? 'ON' : 'OFF'}
            </span>

            <button
              onClick={() => {
                const modes = ['camera', 'screen', 'both', 'none'];
                const currentIdx = modes.indexOf(liveStatus?.video_mode || 'camera');
                const nextMode = modes[(currentIdx + 1) % modes.length];
                handleLiveControl('set_vision_mode', nextMode);
              }}
              title={liveControlError || liveStatus?.errors?.camera || liveStatus?.errors?.screen || 'Click to cycle vision source (camera, screen, both, off)'}
              aria-label={`Vision mode ${liveStatus?.video_mode || 'camera'}. Cycle camera, screen, both, or off.`}
              className="px-2 py-0.5 rounded text-[10px] font-pixl bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 flex items-center gap-1 hover:bg-cyan-500/30 transition"
            >
              <span>👁</span>
              <span>VISION: {liveStatus?.video_mode?.toUpperCase() || 'OFF'} · {liveStatus?.video_mode === 'camera' ? (liveStatus?.camera_active ? (liveStatus?.gemini_connected ? 'STREAM' : 'LOCAL') : 'OFF') : liveStatus?.video_mode === 'screen' ? (liveStatus?.screen_active ? (liveStatus?.gemini_connected ? 'STREAM' : 'LOCAL') : 'OFF') : liveStatus?.video_mode === 'both' ? (liveStatus?.camera_active && liveStatus?.screen_active ? (liveStatus?.gemini_connected ? 'STREAM' : 'LOCAL') : 'PARTIAL') : 'OFF'}</span>
            </button>

            <button
              onClick={() => handleLiveControl('reconnect')}
              title="Click to reconnect Gemini Live session"
              className="px-1.5 py-0.5 rounded text-[10px] font-pixl text-slate-400 hover:text-white hover:bg-white/10 transition"
            >
              <span>⟳</span>
            </button>
          </div>
        </div>
      </div>

      {/* Recruiter 1-Click Demo Strip */}
      <div className="flex-shrink-0">
        <RecruiterStrip onSelectPrompt={(prompt) => {
          setActiveTab('arena');
          handleSendPrompt(prompt);
        }} />
      </div>

      {/* Main Workspace Layout */}
      <main className="flex-1 min-h-0 w-full max-w-7xl mx-auto px-3 sm:px-4 lg:px-6 py-2.5 sm:py-3.5 overflow-hidden flex flex-col min-w-0">
        {activeTab === 'arena' && (
          <div className="flex-1 min-h-0 h-full flex flex-col lg:flex-row gap-3 sm:gap-4 lg:gap-5 w-full min-w-0 overflow-hidden">
            {/* Arena Chat Panel */}
            <div className="flex-1 min-w-0 h-full min-h-0 overflow-hidden flex flex-col">
              <AgentArena
                messages={messages}
                inputPrompt={inputPrompt}
                setInputPrompt={setInputPrompt}
                onSend={() => handleSendPrompt()}
                onVisionMode={setVisionMode}
                visionMode={liveStatus?.video_mode || 'camera'}
                onClear={() => setMessages([])}
                isExecuting={isExecuting}
                currentStep={currentStep}
                activeTool={activeTool}
                isAgentMode={isAgentMode}
                modelName={telemetry?.normal_mode_model || telemetry?.model}
                sessionId={activeSessionId}
              />
            </div>

            {/* Right HUD Sidebar */}
            <AgentHud
              currentStep={currentStep}
              activeTool={activeTool}
              tools={tools}
              onRefreshTools={fetchTools}
              isOpen={isHudOpen}
              onClose={() => setIsHudOpen(false)}
            />
          </div>
        )}

        {activeTab === 'sessions' && (
          <div className="flex-1 min-h-0 h-full overflow-hidden">
            <SessionsExplorer
              sessions={sessions}
              activeSessionId={activeSessionId}
              activeSessionData={activeSessionData}
              onSelectSession={(sId) => {
                setActiveSessionId(sId);
                fetchSessionDetail(sId);
              }}
              onResumeSession={handleResumeSession}
              onDeleteSession={handleDeleteSession}
              isLoading={false}
            />
          </div>
        )}

        {activeTab === 'traces' && (
          <div className="flex-1 min-h-0 h-full overflow-hidden">
            <TraceReplay
              events={events}
              onInspectPayload={(evt) => {
                setSelectedEvent(evt);
                setPayloadModalOpen(true);
              }}
              isLoading={false}
            />
          </div>
        )}

        {activeTab === 'sql' && (
          <div className="flex-1 min-h-0 h-full overflow-hidden">
            <SqlPlayground
              onExecuteQuery={handleExecuteSql}
              results={sqlResults}
              isLoading={sqlLoading}
              error={sqlError}
            />
          </div>
        )}
      </main>

      {/* Modals */}
      <AgentAuthModal
        isOpen={authModalOpen}
        onClose={() => setAuthModalOpen(false)}
        onAuthenticate={handleAuthenticate}
        error={authError}
      />

      <TechSpecsModal
        isOpen={techSpecsOpen}
        onClose={() => setTechSpecsOpen(false)}
      />

      <PayloadModal
        isOpen={payloadModalOpen}
        onClose={() => setPayloadModalOpen(false)}
        event={selectedEvent}
      />

    </div>
  );
}
