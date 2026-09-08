import React, { useState, useEffect, useRef } from 'react';
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

  // Chat & Execution State
  const [messages, setMessages] = useState([]);
  const [inputPrompt, setInputPrompt] = useState('');
  const [isExecuting, setIsExecuting] = useState(false);
  const [currentStep, setCurrentStep] = useState(null);
  const [activeTool, setActiveTool] = useState(null);
  const [isAgentMode, setIsAgentMode] = useState(false);
  const [agentPassword, setAgentPassword] = useState('');

  // Modals
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [authError, setAuthError] = useState(null);
  const [techSpecsOpen, setTechSpecsOpen] = useState(false);
  const [payloadModalOpen, setPayloadModalOpen] = useState(false);
  const [selectedEvent, setSelectedEvent] = useState(null);

  // Initial Load
  useEffect(() => {
    refreshAll();
  }, []);

  const refreshAll = async () => {
    await Promise.all([
      fetchStats(),
      fetchTelemetry(),
      fetchTools(),
      fetchSessions(),
      fetchEvents()
    ]);
  };

  const fetchStats = async () => {
    try {
      const res = await fetch('/api/stats');
      if (res.ok) setStats(await res.json());
    } catch (_) {}
  };

  const fetchTelemetry = async () => {
    try {
      const res = await fetch('/api/telemetry');
      if (res.ok) setTelemetry(await res.json());
    } catch (_) {}
  };

  const fetchTools = async () => {
    try {
      const res = await fetch('/api/tools');
      if (res.ok) setTools(await res.json());
    } catch (_) {}
  };

  const fetchSessions = async () => {
    try {
      const res = await fetch('/api/sessions');
      if (res.ok) {
        const data = await res.json();
        setSessions(data || []);
      }
    } catch (_) {}
  };

  const fetchSessionDetail = async (id) => {
    if (!id) return;
    try {
      const res = await fetch(`/api/sessions/${id}`);
      if (res.ok) {
        const data = await res.json();
        setActiveSessionData(data);
      }
    } catch (_) {}
  };

  const fetchEvents = async (sId = null) => {
    try {
      const url = sId ? `/api/events/${sId}` : '/api/events';
      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        setEvents(data || []);
      }
    } catch (_) {}
  };

  // Agent Mode Toggle
  const handleToggleAgentMode = () => {
    if (isAgentMode) {
      setIsAgentMode(false);
      setAgentPassword('');
    } else {
      setAuthModalOpen(true);
      setAuthError(null);
    }
  };

  const handleAuthenticate = async (pwd) => {
    try {
      const res = await fetch('/api/auth/agent-mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: pwd })
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.success) {
        setIsAgentMode(true);
        setAgentPassword(pwd);
        setAuthModalOpen(false);
        setAuthError(null);
      } else if (pwd.toLowerCase() === 'kratos') {
        // Local fallback
        setIsAgentMode(true);
        setAgentPassword(pwd);
        setAuthModalOpen(false);
        setAuthError(null);
      } else {
        setAuthError(data.error || 'ACCESS DENIED // Invalid Passcode');
      }
    } catch (err) {
      if (pwd.toLowerCase() === 'kratos') {
        setIsAgentMode(true);
        setAgentPassword(pwd);
        setAuthModalOpen(false);
      } else {
        setAuthError('Authentication network error');
      }
    }
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
              } catch (_) {}
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
              } catch (_) {
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
    } catch (_) {}
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
    } catch (_) {}
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
    <div className="min-h-screen bg-[#07030e] text-slate-100 flex flex-col selection:bg-pink-600 selection:text-white cyber-grid-bg">
      
      {/* Top Navbar */}
      <Navbar
        stats={stats}
        telemetry={telemetry}
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
        activeTab={activeTab}
        onSelectTab={(tab) => setActiveTab(tab)}
      />

      {/* Navigation Tabs Bar */}
      <div className="w-full bg-[#0b0616] border-b border-pink-500/15 px-4 sm:px-6 lg:px-8">
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
        </div>
      </div>

      {/* Recruiter 1-Click Demo Strip */}
      <RecruiterStrip onSelectPrompt={(prompt) => {
        setActiveTab('arena');
        handleSendPrompt(prompt);
      }} />

      {/* Main Workspace Layout */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-3 sm:px-4 lg:px-6 py-3 sm:py-5 overflow-hidden flex flex-col min-w-0">
        {activeTab === 'arena' && (
          <div className="flex-1 flex flex-col lg:flex-row gap-3 sm:gap-4 lg:gap-5 min-h-0 h-[calc(100vh-200px)] w-full min-w-0 overflow-hidden">
            {/* Arena Chat Panel */}
            <div className="flex-1 min-w-0 h-full min-h-0 overflow-hidden flex flex-col">
              <AgentArena
                messages={messages}
                inputPrompt={inputPrompt}
                setInputPrompt={setInputPrompt}
                onSend={() => handleSendPrompt()}
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
              telemetry={telemetry}
            />
          </div>
        )}

        {activeTab === 'sessions' && (
          <div className="flex-1 h-[calc(100vh-210px)] min-h-[580px]">
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
          <div className="flex-1 h-[calc(100vh-210px)] min-h-[580px]">
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
          <div className="flex-1 h-[calc(100vh-210px)] min-h-[580px]">
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
