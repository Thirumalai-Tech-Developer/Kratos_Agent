import React, { useState, useEffect, useRef } from 'react';
import Navbar from './components/Navbar';
import AgentArena from './components/AgentArena';
import AgentHud from './components/AgentHud';
import SessionsExplorer from './components/SessionsExplorer';
import TraceReplay from './components/TraceReplay';
import SqlPlayground from './components/SqlPlayground';
import WorkspaceCommands from './components/WorkspaceCommands';
import ChangesReview from './components/ChangesReview';
import ModelSettings from './components/ModelSettings';
import ModelPicker from './components/ModelPicker';
import JobsWorkspace from './components/JobsWorkspace';
import { AgentAuthModal, TechSpecsModal, PayloadModal } from './components/Modals';
import WorkspaceSidebar from './components/WorkspaceSidebar';
import ProjectInstructions from './components/ProjectInstructions';
import { currentToolActivities, mergeWorkspaceEvents, runningToolActivities } from './workspaceActivity';

import { apiFetch } from './api';
import { getUserProfile } from './userProfile';
import { modelModalityLabel, normalizeModelCatalog, withSelectedCatalogModel } from './modelCatalog';
import { isToolEvent, updateToolActivity, finishToolActivity } from './chatActivity';
import { isRecoveryEvent, isToolFormatFailure } from './chatRecovery';
import { finalizeTimelineText, finishActorTimelineTools, finishTimelineTools, messageTimeline, resolveTimelineTool, savedMessageTimeline, syncTimelineText, timelineToolStart } from './messageTimeline';
import { toolCardAnchor } from './toolAnchors';

export default function App() {
  // Navigation
  const [activeTab, setActiveTab] = useState('arena');
  const [isHudOpen, setIsHudOpen] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [instructionsOpen, setInstructionsOpen] = useState(false);
  const [commandsOpen, setCommandsOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [modelPickerOpen, setModelPickerOpen] = useState(false);
  const [currentModel, setCurrentModel] = useState(null);
  const [modelCatalog, setModelCatalog] = useState([]);
  const [modelCatalogLoaded, setModelCatalogLoaded] = useState(false);
  const [modelCatalogLoading, setModelCatalogLoading] = useState(true);
  const [modelCatalogError, setModelCatalogError] = useState('');
  const [modelCatalogNotices, setModelCatalogNotices] = useState([]);
  const modelCatalogRequestedRef = useRef(false);
  const modelCatalogRequestRef = useRef(null);
  const modelCatalogWaitingForWorkspaceRef = useRef(false);

  useEffect(() => {
    const onShortcut = event => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setCommandsOpen(open => !open);
      }
    };
    window.addEventListener('keydown', onShortcut);
    return () => window.removeEventListener('keydown', onShortcut);
  }, []);

  // Core Data State
  const [stats, setStats] = useState(null);
  const [telemetry, setTelemetry] = useState(null);
  const [contextUsage, setContextUsage] = useState(null);
  const [isCompacting, setIsCompacting] = useState(false);
  const [contextNotice, setContextNotice] = useState('');
  const [contextError, setContextError] = useState('');
  const [tools, setTools] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const activeSessionRef = useRef(null);
  const eventScopeVersionRef = useRef(0);
  const [activeSessionData, setActiveSessionData] = useState(null);
  const [events, setEvents] = useState([]);
  const [sqlResults, setSqlResults] = useState([]);
  const [sqlLoading, setSqlLoading] = useState(false);
  const [sqlError, setSqlError] = useState(null);
  const [liveStatus, setLiveStatus] = useState(null);
  const [liveControlError, setLiveControlError] = useState(null);
  const [liveControlPending, setLiveControlPending] = useState(null);
  const liveRequestRef = useRef(null);
  const liveStatusEpochRef = useRef(0);

  // Chat & Execution State
  const [messages, setMessages] = useState([]);
  const localMessageSequenceRef = useRef(0);
  const [inputPrompt, setInputPrompt] = useState('');
  const [isExecuting, setIsExecuting] = useState(false);
  const [isCreatingSession, setIsCreatingSession] = useState(false);
  const sessionCreationRef = useRef(null);
  const [isStopping, setIsStopping] = useState(false);
  const [executionError, setExecutionError] = useState('');
  const [recoveryNotice, setRecoveryNotice] = useState(null);
  const recoveryActiveRef = useRef(false);
  const [connectionInterrupted, setConnectionInterrupted] = useState(false);
  const [isWorkspaceStarting, setIsWorkspaceStarting] = useState(false);
  const executionRef = useRef(null);
  const [currentStep, setCurrentStep] = useState(null);
  const [activeTool, setActiveTool] = useState(null);
  const [activeTurnId, setActiveTurnId] = useState(null);
  const [isAgentMode, setIsAgentMode] = useState(true);
  const [agentPassword, setAgentPassword] = useState('kratos');

  // A disconnected response is not proof that the worker stopped. Keep sending
  // disabled until the runtime confirms it is idle, including after a refresh.
  useEffect(() => {
    let disposed = false;
    const checkExecution = async () => {
      try {
        const response = await apiFetch('/api/health');
        const health = response.ok ? await response.json() : null;
        if (disposed || !health || typeof health.busy !== 'boolean') return;
        if (sessionCreationRef.current) return;
        if (health.starting) {
          setIsWorkspaceStarting(true);
          setExecutionError('Preparing your user workspace…');
          return;
        }
        if (isWorkspaceStarting) {
          setIsWorkspaceStarting(false);
          setExecutionError('');
          refreshAll();
          // A starting worker has not read its catalog yet. Permit its first
          // local read once ready; auth/network failures still require Refetch.
          if (modelCatalogWaitingForWorkspaceRef.current) {
            modelCatalogWaitingForWorkspaceRef.current = false;
            modelCatalogRequestedRef.current = false;
          }
          fetchModelCatalog();
        }
        if (health.busy && !executionRef.current) {
          setIsExecuting(true);
          setConnectionInterrupted(true);
          setExecutionError('A task is still active in the runtime. Stop it here or wait for it to finish.');
        } else if (!health.busy && connectionInterrupted) {
          const index = executionRef.current?.index;
          if (index != null) setMessages(previous => previous.map((message, i) => i === index ? {
            ...message, status: 'interrupted', isThinking: false, tools: finishToolActivity(message.tools, 'unknown'),
            timeline: finishTimelineTools(message.timeline, 'unknown'),
          } : message));
          executionRef.current = null;
          setIsExecuting(false);
          setIsStopping(false);
          setConnectionInterrupted(false);
          setExecutionError('The runtime is idle. The disconnected response may be incomplete; review Activity or resume the session.');
          refreshAll();
        }
      } catch {
        if (!disposed && connectionInterrupted) setExecutionError('Connection lost. Waiting for the runtime to confirm the task has stopped.');
      }
    };
    checkExecution();
    const interval = connectionInterrupted || isWorkspaceStarting ? setInterval(checkExecution, 2000) : null;
    return () => { disposed = true; if (interval) clearInterval(interval); };
  }, [connectionInterrupted, isWorkspaceStarting]);

  const handleStop = async () => {
    if (!isExecuting || isStopping) return;
    setIsStopping(true);
    setExecutionError('');
    setRecoveryNotice(null);
    try {
      const response = await apiFetch('/api/chat/cancel', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: activeSessionId }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.error || `Stop request failed (${response.status}).`);
      setCurrentStep({ tag: 'STOPPING', label: 'Stop requested. Waiting for the running operation to exit.' });
      // Keep the original stream alive so its terminal status acknowledges stop.
    } catch (error) {
      setIsStopping(false);
      setExecutionError(`${error.message || 'Could not request stop.'} The task may still be running. Try Stop again.`);
    }
  };

  // Modals
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [authError, setAuthError] = useState(null);
  const [techSpecsOpen, setTechSpecsOpen] = useState(false);
  const [payloadModalOpen, setPayloadModalOpen] = useState(false);
  const [selectedEvent, setSelectedEvent] = useState(null);

  const fetchStats = async () => {
    try {
      const res = await apiFetch('/api/stats');
      if (res.ok) setStats(await res.json());
    } catch {}
  };

  const fetchTelemetry = async () => {
    try {
      const res = await apiFetch('/api/telemetry');
      if (res.ok) {
        const data = await res.json();
        setTelemetry(data);
        if (data.normal_mode_model || data.model) setCurrentModel(data.normal_mode_model || data.model);
      }
    } catch {}
  };

  const fetchTools = async () => {
    try {
      const res = await apiFetch('/api/tools');
      if (res.ok) setTools(await res.json());
    } catch {}
  };

  const fetchContext = async () => {
    try {
      const response = await apiFetch('/api/context');
      if (response.ok) setContextUsage(await response.json());
    } catch {}
  };

  const handleCompactContext = async () => {
    if (isExecuting || isCompacting) return;
    setIsCompacting(true);
    setContextError('');
    setContextNotice('');
    try {
      const response = await apiFetch('/api/context/compact', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: contextUsage?.session_id }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.error || `Compaction failed (${response.status}).`);
      setContextUsage(result.context);
      setContextNotice(result.message);
    } catch (error) {
      setContextError(error.message || 'Could not compact context.');
    } finally {
      setIsCompacting(false);
    }
  };

  const fetchModelCatalog = ({ refresh = false } = {}) => {
    if (modelCatalogRequestRef.current) return modelCatalogRequestRef.current.promise;
    // A successful empty catalog is still loaded. Reopening dialogs, health
    // checks and telemetry updates must not turn into upstream catalog polls.
    if (!refresh && modelCatalogRequestedRef.current) return Promise.resolve();
    modelCatalogRequestedRef.current = true;
    const request = { controller: new AbortController(), promise: null };
    modelCatalogRequestRef.current = request;
    setModelCatalogLoading(true);
    setModelCatalogError('');
    request.promise = (async () => {
      try {
        const response = await apiFetch(`/api/models${refresh ? '?refresh=1' : ''}`, { signal: request.controller.signal });
        const data = await response.json().catch(() => ({}));
        if (request.controller.signal.aborted) return;
        if (!refresh && response.status === 503 && data.starting === true) {
          modelCatalogWaitingForWorkspaceRef.current = true;
          setIsWorkspaceStarting(true);
          return;
        }
        if (!response.ok) throw new Error(data.error || `Models could not be loaded (${response.status}).`);
        const catalog = normalizeModelCatalog(data.models);
        if (request.controller.signal.aborted) return;
        setModelCatalog(catalog);
        setModelCatalogLoaded(true);
        setModelCatalogNotices(Array.isArray(data.notices) ? data.notices.filter(message => typeof message === 'string') : []);
        if (typeof data.model === 'string' && data.model) setCurrentModel(data.model);
      } catch (failure) {
        if (!request.controller.signal.aborted) setModelCatalogError(failure.message || 'Could not reach the model catalog.');
      } finally {
        if (modelCatalogRequestRef.current === request) {
          modelCatalogRequestRef.current = null;
          setModelCatalogLoading(modelCatalogWaitingForWorkspaceRef.current);
        }
      }
    })();
    return request.promise;
  };

  const fetchSessions = async () => {
    try {
      const res = await apiFetch('/api/sessions');
      if (res.ok) {
        const data = await res.json();
        setSessions(data || []);
      }
    } catch {}
  };

  const fetchSessionDetail = async (id) => {
    if (!id) return;
    try {
      const res = await apiFetch(`/api/sessions/${id}`);
      if (res.ok) {
        const data = await res.json();
        setActiveSessionData(data);
      }
    } catch {}
  };

  const fetchEvents = async (sId = activeSessionRef.current) => {
    const version = eventScopeVersionRef.current;
    try {
      const url = sId ? `/api/events/${sId}` : '/api/events';
      const res = await apiFetch(url);
      if (res.ok) {
        const data = await res.json();
        if (version !== eventScopeVersionRef.current || sId !== activeSessionRef.current) return;
        setEvents(previous => sId ? mergeWorkspaceEvents(previous, data) : (Array.isArray(data) ? data : []));
      }
    } catch {}
  };

  const fetchLiveStatus = async () => {
    const epoch = liveStatusEpochRef.current;
    try {
      const res = await apiFetch('/api/live/status');
      if (res.ok) {
        const data = await res.json();
        if (epoch === liveStatusEpochRef.current && !liveRequestRef.current) setLiveStatus(data);
      }
    } catch {}
  };

  async function refreshAll() {
    await Promise.all([
      fetchStats(),
      fetchTelemetry(),
      fetchContext(),
      fetchTools(),
      fetchSessions(),
      fetchEvents(),
      fetchLiveStatus()
    ]);
  }

  // Initial Load & polling
  useEffect(() => {
    const initialRefresh = setTimeout(refreshAll, 0);
    const initialModels = setTimeout(fetchModelCatalog, 0);
    const interval = setInterval(fetchLiveStatus, 3000);
    const contextInterval = setInterval(fetchContext, 3000);
    return () => {
      clearTimeout(initialRefresh);
      clearTimeout(initialModels);
      clearInterval(interval);
      clearInterval(contextInterval);
      if (modelCatalogRequestRef.current) {
        modelCatalogRequestRef.current.controller.abort();
        modelCatalogRequestRef.current = null;
        modelCatalogRequestedRef.current = false;
      }
      modelCatalogWaitingForWorkspaceRef.current = false;
    };
  }, []);

  const requestLiveControl = async (action, value = null) => {
    if (liveRequestRef.current) throw new Error('A voice or vision change is already in progress.');
    const request = { action, value };
    liveRequestRef.current = request;
    liveStatusEpochRef.current += 1;
    setLiveControlPending(request);
    setLiveControlError(null);
    try {
      const res = await apiFetch('/api/live/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, value }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `Live control failed (${res.status})`);
      setLiveStatus(data);
      return data;
    } catch (error) {
      setLiveControlError(error.message || 'Could not reach the Live runtime.');
      throw error;
    } finally {
      if (liveRequestRef.current === request) liveRequestRef.current = null;
      setLiveControlPending(null);
    }
  };

  const handleLiveControl = async (action, value = null) => {
    try { await requestLiveControl(action, value); } catch { /* The visible control error retains the failure. */ }
  };

  const setVisionMode = async (mode) => {
    const data = await requestLiveControl('set_vision_mode', mode);
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

  const createSession = () => {
    if (sessionCreationRef.current) return sessionCreationRef.current;
    setIsCreatingSession(true);
    const promise = (async () => {
      await Promise.resolve();
      try {
        const model = currentModel || telemetry?.normal_mode_model || telemetry?.model;
        const response = await apiFetch('/api/sessions', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(model ? { model } : {}) });
        const data = await response.json().catch(() => ({}));
        const id = data.session_id || data.id;
        if (response.status !== 201 || typeof id !== 'string' || !id) throw new Error(data.error || 'A new chat could not be created. Your current chat was kept.');
        return id;
      } finally {
        sessionCreationRef.current = null;
        setIsCreatingSession(false);
      }
    })();
    sessionCreationRef.current = promise;
    return promise;
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
    if (!text || isExecuting || isCompacting || isWorkspaceStarting || sessionCreationRef.current) return;

    const visionCommand = text.match(/^\/vision(?:\s+(.*))?$/i);
    if (visionCommand) {
      const modes = ['camera', 'screen', 'both', 'none'];
      const requestedMode = visionCommand[1]?.toLowerCase().trim();
      const nextMode = requestedMode || modes[(modes.indexOf(liveStatus?.video_mode || 'camera') + 1) % modes.length];
      const userMessage = { role: 'user', content: text, timestamp: new Date().toLocaleTimeString() };
      const responseId = `vision-${++localMessageSequenceRef.current}`;
      setInputPrompt('');
      setMessages((prev) => [...prev, userMessage, {
        role: 'agent',
        id: responseId,
        content: 'Updating vision source…',
        timestamp: new Date().toLocaleTimeString(),
      }]);
      if (requestedMode && ![...modes, 'off'].includes(requestedMode)) {
        setMessages((prev) => {
          const updated = [...prev];
          const lastIndex = updated.findIndex(message => message.id === responseId);
          if (lastIndex >= 0) updated[lastIndex] = { ...updated[lastIndex], content: 'Usage: `/vision camera`, `/vision screen`, `/vision both`, or `/vision off`.' };
          return updated;
        });
        return;
      }
      try {
        const activeMode = await setVisionMode(nextMode === 'off' ? 'none' : nextMode);
        setMessages((prev) => {
          const updated = [...prev];
          const lastIndex = updated.findIndex(message => message.id === responseId);
          const last = updated[lastIndex];
          if (last?.role === 'agent') {
            updated[lastIndex] = {
              ...last,
              content: `Vision source ${activeMode === 'none' || activeMode === 'off' ? 'disabled' : `set to **${activeMode}**`}.`,
            };
          }
          return updated;
        });
      } catch (error) {
        setMessages((prev) => {
          const updated = [...prev];
          const lastIndex = updated.findIndex(message => message.id === responseId);
          const last = updated[lastIndex];
          if (last?.role === 'agent') {
            updated[lastIndex] = { ...last, content: `Could not change vision mode: ${error.message}` };
          }
          return updated;
        });
      }
      return;
    }

    if (!activeSessionRef.current) {
      try {
        const id = await createSession();
        eventScopeVersionRef.current += 1;
        activeSessionRef.current = id;
        setActiveSessionId(id);
        setEvents([]);
        fetchContext();
        fetchSessions();
      } catch (error) {
        setExecutionError(error.message || 'A new chat could not be created.');
        return;
      }
    }

    setInputPrompt('');
    setIsExecuting(true);
    setActiveTurnId(null);
    setIsStopping(false);
    setExecutionError('');
    setRecoveryNotice(null);
    recoveryActiveRef.current = false;
    setConnectionInterrupted(false);
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
    executionRef.current = { index: agentMsgIndex };
    const initialAgentMsg = {
      role: 'agent',
      content: '',
      reasoning: '',
      isThinking: false,
      thinkingDuration: 0,
      tools: [],
      timeline: [],
      status: 'running',
      timestamp: new Date().toLocaleTimeString()
    };
    setMessages((prev) => [...prev, initialAgentMsg]);

    let rawContent = '';
    let accumulatedReasoning = '';
    let isActivelyThinking = false;
    let thinkStartTime = Date.now();
    let thinkingDuration = 0;
    let terminalAcknowledged = false;

    try {
      const payload = {
        session_id: activeSessionRef.current,
        prompt: text,
        message: text,
        query: text,
        mode: isAgentMode ? 'agent' : 'chat',
        agent_mode: isAgentMode,
        is_agent_mode: isAgentMode,
        agent_password: agentPassword
      };

      const res = await apiFetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        terminalAcknowledged = true;
        const errText = await res.text().catch(() => '');
        rawContent = `⚠️ **Error HTTP ${res.status}**: ${errText || 'Edge server error'}`;
        setMessages((prev) => {
          const updated = [...prev];
          updated[agentMsgIndex] = { ...updated[agentMsgIndex], content: rawContent, timeline: finalizeTimelineText(updated[agentMsgIndex].timeline, rawContent), status: 'failed' };
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

                if (data.type === 'context' && data.context) {
                  setContextUsage(data.context);
                  setContextNotice('');
                  setContextError('');
                  continue;
                }

                if (data.type === 'runtime_event' && data.event?.kind) {
                  if (data.event.kind === 'turn.started' && !data.event.payload?.subagent) setActiveTurnId(data.event.turn_id || null);
                  setEvents(previous => mergeWorkspaceEvents(previous, [data.event]));
                  const scope = data.event.payload?.subagent;
                  const activity = data.event.payload?.activity;
                  if (scope?.agent_id && ['tool.started', 'tool.completed', 'tool.failed'].includes(activity?.kind)) {
                    const payload = activity.payload || {};
                    const callId = `${scope.agent_id}:${payload.call_id || payload.id || payload.name}`;
                    const source = { agent_id: scope.agent_id, role: scope.role, task: scope.task };
                    const starting = activity.kind === 'tool.started';
                    const scoped = { ...payload, call_id: callId, source_agent: source,
                      type: starting ? 'tool_call' : activity.kind === 'tool.failed' ? 'tool_failed' : 'tool_result',
                      ...(starting ? { tool_call: { ...payload, call_id: callId, source_agent: source, args: payload.arguments } } : { result: payload.content }),
                    };
                    setMessages(previous => previous.map((message, i) => i === agentMsgIndex ? { ...message,
                      timeline: starting ? timelineToolStart(message.timeline, scoped) : resolveTimelineTool(message.timeline, scoped),
                    } : message));
                  }
                  if (scope?.agent_id && ['subagent.completed', 'subagent.failed'].includes(data.event.kind)) {
                    setMessages(previous => previous.map((message, i) => i === agentMsgIndex ? { ...message,
                      timeline: finishActorTimelineTools(message.timeline, scope.agent_id, scope.status),
                    } : message));
                  }
                  continue;
                }

                if (data.session_id && !activeSessionRef.current) {
                  activeSessionRef.current = data.session_id;
                  setActiveSessionId(data.session_id);
                }

                if (data.type === 'start' && data.model) {
                  setMessages(previous => previous.map((message, i) => i === agentMsgIndex ? { ...message, model: data.model } : message));
                }

                if (isRecoveryEvent(data)) {
                  // Retrying is progress. The runtime owns the retry strategy;
                  // keep this stream and Stop active until it acknowledges a
                  // real terminal state. Repeated retries do not pin the toast.
                  if (!recoveryActiveRef.current) setRecoveryNotice({ attempt: data.attempt });
                  recoveryActiveRef.current = true;
                  setExecutionError('');
                  setCurrentStep(null);
                  setActiveTool(null);
                  setMessages(previous => previous.map((message, i) => i === agentMsgIndex ? {
                    ...message, status: 'running', isThinking: false,
                  } : message));
                  continue;
                }

                if (isToolEvent(data)) {
                  recoveryActiveRef.current = false;
                  setMessages(previous => previous.map((message, i) => i === agentMsgIndex ? {
                    ...message, tools: updateToolActivity(message.tools, data),
                    timeline: data.type === 'tool_call' || data.tool_call ? timelineToolStart(message.timeline, data) : resolveTimelineTool(message.timeline, data),
                  } : message));
                  if (data.type === 'tool_call' || data.tool_call) setActiveTool(data.tool_call || data.name);
                  else setActiveTool(null);
                  // Tool output often has a top-level `result`; it is never the
                  // assistant's final response. Render it inside the tool card.
                  continue;
                }

                if (data.type === 'error') {
                  if (isToolFormatFailure(data.message || data.error)) {
                    if (!recoveryActiveRef.current) setRecoveryNotice({ attempt: data.attempt });
                    recoveryActiveRef.current = true;
                    continue;
                  }
                  setRecoveryNotice(null);
                  setExecutionError(data.message || data.error || 'The task failed.');
                }

                if (data.type === 'done') {
                  terminalAcknowledged = true;
                  setRecoveryNotice(null);
                  const status = data.status || 'completed';
                  setMessages(previous => previous.map((message, i) => i === agentMsgIndex ? {
                    ...message, status, isThinking: false, tools: finishToolActivity(message.tools, status),
                    timeline: finishTimelineTools(message.timeline, status),
                  } : message));
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
                  recoveryActiveRef.current = false;
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
                      timeline: syncTimelineText(updated[agentMsgIndex].timeline, updated[agentMsgIndex].content, parsed.content),
                      reasoning: parsed.reasoning || accumulatedReasoning,
                      isThinking: isActivelyThinking,
                      thinkingDuration
                    };
                    return updated;
                  });
                } else if (data.result || data.reply || data.response || data.content) {
                  const finalTxt = data.result || data.reply || data.response || data.content;
                  if (typeof finalTxt === 'string' && finalTxt) {
                    rawContent = finalTxt;
                  }
                  const parsed = parseThinkTags(rawContent, accumulatedReasoning);
                  setMessages((prev) => {
                    const updated = [...prev];
                    updated[agentMsgIndex] = {
                      ...updated[agentMsgIndex],
                      content: parsed.content,
                      timeline: finalizeTimelineText(updated[agentMsgIndex].timeline, parsed.content),
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
              timeline: finalizeTimelineText(updated[agentMsgIndex].timeline, parsedFinal.content || rawContent),
              reasoning: parsedFinal.reasoning || accumulatedReasoning,
              isThinking: false,
              thinkingDuration: thinkingDuration || (accumulatedReasoning ? Math.max(1, Math.round((Date.now() - thinkStartTime) / 1000)) : 0)
            };
          }
          return updated;
        });
      } else {
        // Standard JSON response
        terminalAcknowledged = true;
        const data = await res.json().catch(() => ({}));
        rawContent = data.result || data.reply || data.response || data.content || JSON.stringify(data);
        if (data.session_id) { activeSessionRef.current = data.session_id; setActiveSessionId(data.session_id); }
        const parsed = parseThinkTags(rawContent, accumulatedReasoning);
        setMessages((prev) => {
          const updated = [...prev];
          updated[agentMsgIndex] = {
            ...updated[agentMsgIndex],
            content: parsed.content,
            timeline: finalizeTimelineText(updated[agentMsgIndex].timeline, parsed.content),
            reasoning: parsed.reasoning || accumulatedReasoning,
            isThinking: false,
            thinkingDuration: 0,
            status: data.status || 'completed'
          };
          return updated;
        });
      }
    } catch (err) {
      setExecutionError(`Connection lost: ${err.message || String(err)}. Checking whether the runtime is still active.`);
    } finally {
      if (terminalAcknowledged) {
        recoveryActiveRef.current = false;
        setRecoveryNotice(null);
        executionRef.current = null;
        setIsExecuting(false);
        setIsStopping(false);
        setCurrentStep(null);
        setActiveTool(null);
      } else {
        setConnectionInterrupted(true);
        setExecutionError('Response disconnected before completion. Checking the runtime; Stop remains available.');
      }
      refreshAll();
    }
  };

  // Resume Session in Arena
  const handleResumeSession = async (sessionId) => {
    if (isExecuting || sessionCreationRef.current) return;
    setExecutionError('');
    setRecoveryNotice(null);
    recoveryActiveRef.current = false;
    eventScopeVersionRef.current += 1;
    activeSessionRef.current = sessionId;
    setActiveSessionId(sessionId);
    setEvents([]);
    fetchEvents(sessionId);
    setActiveTab('arena');
    try {
      const res = await apiFetch(`/api/sessions/${sessionId}`);
      if (res.ok) {
        const data = await res.json();
        if (activeSessionRef.current !== sessionId) return;
        setActiveSessionData(data);
        const turnsList = data.turns || [];
        {
          const restoredMessages = [];
          turnsList.forEach((t) => {
            const userContent = t.user_query || t.user || t.prompt || t.query || '';
            const rawAgentContent = t.agent_reply || t.agent || t.reply || t.response || t.content || '';
            const parsed = parseThinkTags(rawAgentContent);
            const timeline = savedMessageTimeline({ ...t, content: parsed.content });
            const savedTools = timeline.filter(block => block.type === 'tool').map(block => block.activity);

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

            if (rawAgentContent || timeline.length) {
              restoredMessages.push({
                role: 'agent',
                content: parsed.content,
                reasoning: parsed.reasoning || '',
                isThinking: false,
                thinkingDuration: 0,
                tools: savedTools,
                timeline,
                status: t.status || 'completed',
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
      const res = await apiFetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
      if (res.ok) {
        if (activeSessionId === sessionId) {
          activeSessionRef.current = null;
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
      const res = await apiFetch('/api/query', {
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

  const startNewTask = async () => {
    if (isExecuting || sessionCreationRef.current) return;
    let id;
    try { id = await createSession(); }
    catch (error) { setExecutionError(error.message || 'A new chat could not be created.'); return; }
    eventScopeVersionRef.current += 1;
    activeSessionRef.current = id;
    setActiveSessionId(id);
    setActiveSessionData(null);
    setMessages([]);
    setEvents([]);
    setInputPrompt('');
    setExecutionError('');
    setRecoveryNotice(null);
    recoveryActiveRef.current = false;
    setContextNotice('');
    setContextError('');
    setCurrentStep(null);
    setActiveTool(null);
    setActiveTab('arena');
    fetchContext();
    fetchSessions();
  };

  const commands = [
    { id: 'new', label: 'New chat', detail: 'Start a fresh conversation', run: startNewTask, disabled: isExecuting || isCreatingSession },
    { id: 'workspace', label: 'Open workspace', run: () => setActiveTab('arena') },
    { id: 'sessions', label: 'Browse sessions', run: () => { setActiveTab('sessions'); fetchSessions(); } },
    { id: 'activity', label: 'View activity', run: () => { setActiveTab('traces'); fetchEvents(); } },
    { id: 'changes', label: 'Review task changes', detail: 'Inspect diffs and restore files from task checkpoints', run: () => setActiveTab('changes') },
    { id: 'data', label: 'Open data explorer', run: () => setActiveTab('sql') },
    { id: 'instructions', label: 'Project instructions', detail: 'Edit kratos.md for this project', run: () => setInstructionsOpen(true) },
    { id: 'jobs', label: 'AI & ML job applications', detail: 'Find matching roles and manage auto-apply', run: () => setActiveTab('jobs') },
    { id: 'refresh', label: 'Refresh workspace', run: refreshAll },
    { id: 'settings', label: 'Model and execution settings', detail: 'Temperature, thinking effort, and inspection budget', run: () => setSettingsOpen(true) },
    { id: 'model', label: 'Change model', detail: 'Browse models from connected providers', run: () => setModelPickerOpen(true), disabled: isExecuting },
    ...sessions.filter(session => session.session_id).map(session => ({
      id: `session-${session.session_id}`, label: session.title || 'Untitled session',
      detail: `${session.model || 'auto'} · ${session.session_id}`, kind: 'Resume session',
      run: () => handleResumeSession(session.session_id), disabled: isExecuting,
    })),
  ];

  const titles = { arena: 'Chat', sessions: 'All chats', traces: 'Activity', changes: 'Changes', sql: 'Data', jobs: 'Jobs' };
  const chatTitle = sessions.find(session => session.session_id === activeSessionId)?.title
    || (activeSessionId && activeSessionData?.session?.title)
    || messages.find(message => message.role === 'user')?.content?.slice(0, 72) || 'New chat';
  const navigate = tab => {
    setActiveTab(tab);
    if (tab === 'sessions') fetchSessions();
    if (tab === 'traces') fetchEvents();
  };
  const latestAssistant = [...messages].reverse().find(message => message.role !== 'user');
  const commandActivities = latestAssistant ? messageTimeline(latestAssistant).filter(block => block.type === 'tool').map(block => block.activity) : [];
  const focusTool = callId => {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const element = document.getElementById(toolCardAnchor(index, callId));
      if (!element) continue;
      const details = element.querySelector('details');
      if (details) details.open = true;
      const group = element.closest('.tool-activity-group');
      if (group) group.open = true;
      element.scrollIntoView({ behavior: 'smooth', block: 'center' });
      details?.querySelector('summary')?.focus({ preventScroll: true });
      return;
    }
    setActiveTab('traces');
    fetchEvents();
  };

  useEffect(() => {
    if (!isExecuting) return;
    const interval = setInterval(() => fetchEvents(), 3000);
    return () => clearInterval(interval);
  }, [isExecuting]);

  return (
    <div className={`studio-app workspace-shell ${isSidebarOpen ? 'has-chats' : 'focused-chat'}`}>
      <WorkspaceSidebar activeTab={activeTab} sessions={sessions} activeSessionId={activeSessionId} isExecuting={isExecuting || isCreatingSession}
        isOpen={isSidebarOpen} onClose={() => setIsSidebarOpen(false)} onNavigate={navigate} onNewChat={startNewTask}
        onResumeSession={handleResumeSession} onOpenCommands={() => { setCommandsOpen(true); fetchSessions(); }}
        onOpenSettings={() => setSettingsOpen(true)} onOpenInstructions={() => setInstructionsOpen(true)}
        userProfile={getUserProfile().slice(0, 6)} workspaceName={telemetry?.workspace_name} />
      <div className="workspace-center">
        <Navbar stats={stats} isAgentMode={isAgentMode} onToggleAgentMode={handleToggleAgentMode} onRefresh={refreshAll}
          onNewChat={startNewTask}
          isExecuting={isExecuting} onOpenSettings={() => setSettingsOpen(true)} onOpenCommands={() => { setCommandsOpen(true); fetchSessions(); }}
          onOpenTechSpecs={() => setTechSpecsOpen(true)} isHudOpen={isHudOpen} onToggleHud={() => setIsHudOpen(!isHudOpen)}
          isSidebarOpen={isSidebarOpen} onToggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)}
          title={activeTab === 'arena' ? chatTitle : titles[activeTab]} activeTab={activeTab} />
        <main className={`workspace-main ${activeTab === 'arena' ? 'workspace-chat' : 'workspace-view'}`}>
          {activeTab === 'jobs' && <JobsWorkspace />}
          {activeTab === 'changes' && <ChangesReview isExecuting={isExecuting} />}
          {activeTab === 'arena' && <AgentArena
            messages={messages} inputPrompt={inputPrompt} setInputPrompt={setInputPrompt}
            runningTools={isExecuting ? runningToolActivities(messages, events, activeTurnId) : []}
            onSend={() => handleSendPrompt()} onStop={handleStop} onRetry={() => handleSendPrompt('continue')}
            isStopping={isStopping} isWorkspaceStarting={isWorkspaceStarting || isCreatingSession} userProfile={getUserProfile().slice(0, 6)}
            executionError={executionError} recoveryNotice={recoveryNotice} onDismissRecoveryNotice={setRecoveryNotice}
            onOpenActivity={() => { setActiveTab('traces'); fetchEvents(activeSessionId); }}
            onVisionMode={setVisionMode} visionMode={liveStatus?.video_mode || 'none'}
            liveStatus={liveStatus} liveControlError={liveControlError} liveControlPending={liveControlPending} onLiveControl={handleLiveControl}
            onClear={() => { if (!isExecuting) setMessages([]); }} isExecuting={isExecuting}
            currentStep={currentStep} activeTool={currentToolActivities(messages).find(tool => tool.status === 'running') || activeTool} isAgentMode={isAgentMode}
            modelName={currentModel || telemetry?.normal_mode_model || telemetry?.model}
            contextUsage={contextUsage} onCompactContext={handleCompactContext} isCompacting={isCompacting}
            contextNotice={contextNotice} contextError={contextError}
            taskDetails={<AgentHud currentStep={currentStep} activities={commandActivities} onFocusTool={focusTool}
              availableTools={tools} events={activeSessionId || messages.length ? events : []} isExecuting={isExecuting}
              sessionStatus={latestAssistant?.status} telemetry={telemetry} isOpen={isHudOpen}
              onClose={() => setIsHudOpen(false)} onOpenActivity={() => { setActiveTab('traces'); fetchEvents(); }} />}
            modelModality={modelModalityLabel(modelCatalog.find(model => model.id === (currentModel || telemetry?.normal_mode_model || telemetry?.model)))}
            onOpenModelPicker={() => { if (!isExecuting) setModelPickerOpen(true); }} sessionId={activeSessionId} />}
          {activeTab === 'sessions' && <SessionsExplorer sessions={sessions} activeSessionId={activeSessionId}
            activeSessionData={activeSessionData} onSelectSession={id => { activeSessionRef.current = id; setActiveSessionId(id); fetchSessionDetail(id); }}
            onResumeSession={handleResumeSession} onDeleteSession={handleDeleteSession} isLoading={false} />}
          {activeTab === 'traces' && <TraceReplay events={events}
            onInspectPayload={event => { setSelectedEvent(event); setPayloadModalOpen(true); }} isLoading={false} />}
          {activeTab === 'sql' && <SqlPlayground onExecuteQuery={handleExecuteSql} results={sqlResults} isLoading={sqlLoading} error={sqlError} />}
        </main>
      </div>
      {instructionsOpen && <ProjectInstructions isExecuting={isExecuting} onClose={() => setInstructionsOpen(false)} />}

      {/* Modals */}
      {commandsOpen && <WorkspaceCommands commands={commands} onClose={() => setCommandsOpen(false)} />}
      {settingsOpen && <ModelSettings isExecuting={isExecuting} onClose={() => setSettingsOpen(false)} />}
      {modelPickerOpen && <ModelPicker currentModel={currentModel || telemetry?.normal_mode_model || telemetry?.model}
        models={modelCatalog} catalogLoaded={modelCatalogLoaded} loading={modelCatalogLoading}
        catalogError={modelCatalogError} notices={modelCatalogNotices} onRefetch={() => fetchModelCatalog({ refresh: true })}
        isExecuting={isExecuting} onClose={() => setModelPickerOpen(false)}
        onSelected={async (model, connection) => {
          setCurrentModel(model);
          setModelCatalog(previous => withSelectedCatalogModel(previous, model, connection));
          await Promise.all([fetchStats(), fetchTelemetry()]);
        }} />}
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
