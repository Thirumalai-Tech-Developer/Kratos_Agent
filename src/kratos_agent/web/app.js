/**
 * KRATOS VI · VICE CYBERPUNK CONSOLE & AGENTIC ARENA
 * Client Controller: Live Streaming, Real-time Step Tracking, Active Tool HUD, D1 Explorer
 */

(function () {
    'use strict';

    // Application State
    const state = {
        sessions: [],
        activeSessionId: null,
        activeSessionData: null,
        events: [],
        traceFilter: 'all',
        tools: [],
        telemetry: null,
        stats: null,
        isExecuting: false,
        isAgentMode: false,
        popoverTimer: null
    };

    // DOM Elements Cache
    const el = {
        // Navigation & Status
        topNav: document.getElementById('topNav'),
        statusPill: document.getElementById('statusPill'),
        d1ModeText: document.getElementById('d1ModeText'),
        d1Latency: document.getElementById('d1Latency'),
        d1DbId: document.getElementById('d1DbId'),
        statSessionsCount: document.getElementById('statSessionsCount'),
        statTurnsCount: document.getElementById('statTurnsCount'),
        statEventsCount: document.getElementById('statEventsCount'),
        statToolsCount: document.getElementById('statToolsCount'),
        btnRefresh: document.getElementById('btnRefresh'),
        btnNewSession: document.getElementById('btnNewSession'),
        btnTechSpecs: document.getElementById('btnTechSpecs'),

        // Agent Mode Switch & Popover
        btnAgentModeToggle: document.getElementById('btnAgentModeToggle'),
        agentModeLed: document.getElementById('agentModeLed'),
        agentModeText: document.getElementById('agentModeText'),
        modePopover: document.getElementById('modePopover'),
        btnCloseModePopover: document.getElementById('btnCloseModePopover'),
        btnContinueChat: document.getElementById('btnContinueChat'),
        btnHudToggle: document.getElementById('btnHudToggle'),
        btnCloseHudDrawer: document.getElementById('btnCloseHudDrawer'),
        arenaHudPanel: document.getElementById('arenaHudPanel'),

        // Tabs
        tabBtns: document.querySelectorAll('.tab-btn'),
        tabPanes: document.querySelectorAll('.tab-pane'),
        tabBadgeTurns: document.getElementById('tabBadgeTurns'),
        tabBadgeEvents: document.getElementById('tabBadgeEvents'),

        // Recruiter Demo Pills
        demoPills: document.querySelectorAll('.demo-pill'),

        // Tab 1: Agent Arena
        arenaMessages: document.getElementById('arenaMessages'),
        welcomeCard: document.getElementById('welcomeCard'),
        arenaInput: document.getElementById('arenaInput'),
        btnSendPrompt: document.getElementById('btnSendPrompt'),
        btnClearChat: document.getElementById('btnClearChat'),
        arenaModelBadge: document.getElementById('arenaModelBadge'),
        arenaStatusBadge: document.getElementById('arenaStatusBadge'),
        arenaSessionLabel: document.getElementById('arenaSessionLabel'),

        // Right HUD Gauges
        currentStepTag: document.getElementById('currentStepTag'),
        currentStepLabel: document.getElementById('currentStepLabel'),
        stepLiveDot: document.getElementById('stepLiveDot'),
        nodeReasoning: document.getElementById('nodeReasoning'),
        nodePlanning: document.getElementById('nodePlanning'),
        nodeToolCall: document.getElementById('nodeToolCall'),
        nodeVerifying: document.getElementById('nodeVerifying'),
        toolInFlightBadge: document.getElementById('toolInFlightBadge'),
        activeToolContent: document.getElementById('activeToolContent'),
        toolsArsenalList: document.getElementById('toolsArsenalList'),
        arsenalCount: document.getElementById('arsenalCount'),
        btnRefreshTools: document.getElementById('btnRefreshTools'),
        telemRuntime: document.getElementById('telemRuntime'),
        telemWorkspace: document.getElementById('telemWorkspace'),
        telemStorage: document.getElementById('telemStorage'),
        telemGateway: document.getElementById('telemGateway'),

        // Tab 2: Sessions & Turns
        sessionSearch: document.getElementById('sessionSearch'),
        sessionList: document.getElementById('sessionList'),
        activeSessionTitle: document.getElementById('activeSessionTitle'),
        activeModelBadge: document.getElementById('activeModelBadge'),
        activeStatusBadge: document.getElementById('activeStatusBadge'),
        activeUpdatedBadge: document.getElementById('activeUpdatedBadge'),
        activeIdBadge: document.getElementById('activeIdBadge'),
        btnDeleteSession: document.getElementById('btnDeleteSession'),
        chatContainer: document.getElementById('chatContainer'),

        // Tab 3: Trace Timeline
        timelineContainer: document.getElementById('timelineContainer'),
        eventCountDisplay: document.getElementById('eventCountDisplay'),
        filterChips: document.querySelectorAll('.filter-chip'),

        // Tab 4: SQL Playground
        sqlEditor: document.getElementById('sqlEditor'),
        btnRunSql: document.getElementById('btnRunSql'),
        sqlResultsMeta: document.getElementById('sqlResultsMeta'),
        sqlTableContainer: document.getElementById('sqlTableContainer'),
        presetBtns: document.querySelectorAll('.preset-btn'),

        // Modals
        payloadModal: document.getElementById('payloadModal'),
        modalEventTitle: document.getElementById('modalEventTitle'),
        modalEventJson: document.getElementById('modalEventJson'),
        btnCloseModal: document.getElementById('btnCloseModal'),
        techSpecsModal: document.getElementById('techSpecsModal'),
        btnCloseTechSpecs: document.getElementById('btnCloseTechSpecs')
    };

    // Initialize Application
    async function init() {
        bindEvents();
        updateAgentModeUI(false);
        if (window.hljs && typeof window.hljs.highlightAll === 'function') {
            try { window.hljs.highlightAll(); } catch (_) {}
        }
        await Promise.all([
            loadStats(),
            loadTelemetry(),
            loadTools(),
            loadSessions()
        ]);
    }

    // Bind Event Listeners
    function bindEvents() {
        // Agent Mode Switch Toggle
        if (el.btnAgentModeToggle) {
            el.btnAgentModeToggle.addEventListener('click', (e) => {
                e.stopPropagation();
                toggleAgentMode();
            });
        }
        if (el.btnCloseModePopover) {
            el.btnCloseModePopover.addEventListener('click', (e) => {
                e.stopPropagation();
                if (el.modePopover) el.modePopover.classList.add('d-none');
            });
        }
        // Close popover when clicking outside
        document.addEventListener('click', (e) => {
            if (el.modePopover && !el.modePopover.classList.contains('d-none')) {
                if (!el.modePopover.contains(e.target) && !el.btnAgentModeToggle.contains(e.target)) {
                    el.modePopover.classList.add('d-none');
                }
            }
        });

        // Tab switching
        el.tabBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const targetTab = btn.getAttribute('data-tab');
                switchTab(targetTab);
            });
        });

        // Prompt input dispatch
        el.btnSendPrompt.addEventListener('click', () => handleDispatch());
        el.arenaInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleDispatch();
            }
        });

        // Recruiter demo shortcut pills
        el.demoPills.forEach(pill => {
            pill.addEventListener('click', () => {
                const prompt = pill.getAttribute('data-prompt');
                if (prompt) {
                    el.arenaInput.value = prompt;
                    handleDispatch();
                }
            });
        });

        // Clear chat view
        el.btnClearChat.addEventListener('click', () => {
            el.arenaMessages.innerHTML = '';
            if (el.welcomeCard) el.arenaMessages.appendChild(el.welcomeCard);
        });

        // Refresh buttons
        el.btnRefresh.addEventListener('click', async () => {
            el.btnRefresh.style.transform = 'rotate(180deg)';
            await Promise.all([loadStats(), loadTelemetry(), loadSessions()]);
            if (state.activeSessionId) await selectSession(state.activeSessionId);
            setTimeout(() => { el.btnRefresh.style.transform = 'none'; }, 300);
        });

        el.btnRefreshTools.addEventListener('click', () => loadTools());
        el.btnNewSession.addEventListener('click', handleCreateNewSession);
        el.btnDeleteSession.addEventListener('click', handleDeleteActiveSession);
        if (el.btnContinueChat) {
            el.btnContinueChat.addEventListener('click', () => {
                if (state.activeSessionId) continueChatFromSession(state.activeSessionId);
            });
        }

        // Mobile HUD drawer toggle
        if (el.btnHudToggle && el.arenaHudPanel) {
            el.btnHudToggle.addEventListener('click', () => {
                el.arenaHudPanel.classList.toggle('open-drawer');
            });
        }
        if (el.btnCloseHudDrawer && el.arenaHudPanel) {
            el.btnCloseHudDrawer.addEventListener('click', () => {
                el.arenaHudPanel.classList.remove('open-drawer');
            });
        }

        // Tech specs modal
        el.btnTechSpecs.addEventListener('click', () => el.techSpecsModal.classList.add('open'));
        el.btnCloseTechSpecs.addEventListener('click', () => el.techSpecsModal.classList.remove('open'));
        el.techSpecsModal.addEventListener('click', (e) => {
            if (e.target === el.techSpecsModal) el.techSpecsModal.classList.remove('open');
        });

        // Session search
        el.sessionSearch.addEventListener('input', (e) => {
            renderSessionList(e.target.value.toLowerCase().trim());
        });

        // Trace filter chips
        el.filterChips.forEach(chip => {
            chip.addEventListener('click', () => {
                el.filterChips.forEach(c => c.classList.remove('active'));
                chip.classList.add('active');
                state.traceFilter = chip.getAttribute('data-filter');
                renderTimeline();
            });
        });

        // SQL Playground
        el.presetBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const query = btn.getAttribute('data-sql');
                if (query) {
                    el.sqlEditor.value = query;
                    executeSql();
                }
            });
        });
        el.btnRunSql.addEventListener('click', executeSql);
        el.sqlEditor.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                e.preventDefault();
                executeSql();
            }
        });

        // Payload modal
        el.btnCloseModal.addEventListener('click', () => el.payloadModal.classList.remove('open'));
        el.payloadModal.addEventListener('click', (e) => {
            if (e.target === el.payloadModal) el.payloadModal.classList.remove('open');
        });

        // Esc key closes modals
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                el.payloadModal.classList.remove('open');
                el.techSpecsModal.classList.remove('open');
            }
        });
    }

    // ==========================================================================
    // AGENT MODE CONTROLLER (ON: Autonomous Tools / OFF: Static Normal Chat)
    // ==========================================================================

    function toggleAgentMode() {
        state.isAgentMode = !state.isAgentMode;
        updateAgentModeUI(true);
    }

    function updateAgentModeUI(showPopoverIfStatic = false) {
        if (state.popoverTimer) {
            clearTimeout(state.popoverTimer);
            state.popoverTimer = null;
        }

        const agentModel = (state.telemetry && state.telemetry.model) ? state.telemetry.model : 'auto';
        const normalModel = (state.telemetry && state.telemetry.normal_mode_model) ? state.telemetry.normal_mode_model : 'deepseek-web/deepseek-v4-pro';

        if (state.isAgentMode) {
            if (el.btnAgentModeToggle) {
                el.btnAgentModeToggle.className = 'btn btn-mode-toggle active-agent';
                el.btnAgentModeToggle.title = 'Autonomous Agent Mode active (Terminal & tools enabled)';
            }
            if (el.agentModeText) {
                el.agentModeText.textContent = 'AGENT MODE: ON';
            }
            if (el.modePopover) {
                el.modePopover.classList.add('d-none');
            }
            if (el.metaMode) {
                el.metaMode.textContent = 'AUTONOMOUS AGENT';
            }
            if (el.arenaModelBadge) {
                el.arenaModelBadge.textContent = `Model: ${agentModel}`;
            }
        } else {
            if (el.btnAgentModeToggle) {
                el.btnAgentModeToggle.className = 'btn btn-mode-toggle active-static';
                el.btnAgentModeToggle.title = 'Agent Mode: OFF (Static Normal Chat Mode · Hosted Demo)';
            }
            if (el.agentModeText) {
                el.agentModeText.textContent = 'AGENT MODE: OFF';
            }
            if (el.metaMode) {
                el.metaMode.textContent = 'RESTRICTED CHAT';
            }
            if (el.arenaModelBadge) {
                el.arenaModelBadge.textContent = `Model: ${normalModel}`;
            }
            if (showPopoverIfStatic && el.modePopover) {
                el.modePopover.classList.remove('d-none');
                state.popoverTimer = setTimeout(() => {
                    if (el.modePopover) el.modePopover.classList.add('d-none');
                }, 7000);
            }
        }
    }

    // Tab Switching
    function switchTab(tabId) {
        el.tabBtns.forEach(btn => {
            btn.classList.toggle('active', btn.getAttribute('data-tab') === tabId);
        });
        el.tabPanes.forEach(pane => {
            pane.classList.toggle('active', pane.id === tabId);
        });
    }

    // ==========================================================================
    // LIVE AGENT EXECUTION & STREAMING (Server-Sent Events)
    // ==========================================================================

    async function handleDispatch() {
        const prompt = el.arenaInput.value.trim();
        if (!prompt || state.isExecuting) return;

        state.isExecuting = true;
        el.btnSendPrompt.disabled = true;
        el.arenaStatusBadge.textContent = 'EXECUTING';
        el.arenaStatusBadge.className = 'badge badge-id';

        // Hide welcome card once chat starts
        if (el.welcomeCard && el.welcomeCard.parentNode) {
            el.welcomeCard.style.display = 'none';
        }

        // 1. Render User Message
        appendChatMessage('user', prompt);
        el.arenaInput.value = '';

        // 2. Prepare Assistant Streaming Message Bubble
        const assistantBubble = appendChatMessage('assistant', '');
        const contentEl = assistantBubble.querySelector('.message-content');
        let accumulatedText = '';

        // Update HUD to Reasoning
        updateStep('reasoning', 'Analyzing prompt & classifying intent...');

        try {
            const res = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    prompt,
                    session_id: state.activeSessionId,
                    agent_mode: state.isAgentMode
                })
            });

            if (!res.ok) throw new Error(`HTTP ${res.status}`);

            const reader = res.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop(); // Retain incomplete line

                for (const line of lines) {
                    const trimmed = line.trim();
                    if (!trimmed || !trimmed.startsWith('data: ')) continue;
                    const jsonStr = trimmed.slice(6);
                    try {
                        const event = JSON.parse(jsonStr);
                        handleStreamEvent(event, assistantBubble, contentEl, (txt) => {
                            accumulatedText += txt;
                            contentEl.innerHTML = formatMarkdownLike(accumulatedText) + '<span class="streaming-cursor">▊</span>';
                            el.arenaMessages.scrollTop = el.arenaMessages.scrollHeight;
                        }, accumulatedText);
                    } catch (e) {
                        // ignore keep-alive or ping parse errors
                    }
                }
            }

            // Remove streaming cursor once reading completes
            if (accumulatedText) {
                contentEl.innerHTML = formatMarkdownLike(accumulatedText);
            }
        } catch (err) {
            console.error('Chat execution error:', err);
            contentEl.innerHTML = `<span style="color:var(--spartan-crimson)">❌ Execution Error: ${escapeHtml(err.message)}</span>`;
        } finally {
            state.isExecuting = false;
            el.btnSendPrompt.disabled = false;
            el.arenaStatusBadge.textContent = 'READY';
            el.arenaStatusBadge.className = 'badge badge-status';
            resetHudStandby();

            // Refresh sessions & stats in background
            await loadStats();
            await loadSessions();
        }
    }

    // Handle SSE Stream Events
    function handleStreamEvent(event, assistantBubble, contentEl, onToken, accumulatedText = '') {
        switch (event.type) {
            case 'start':
                if (event.session_id) {
                    state.activeSessionId = event.session_id;
                    if (el.arenaSessionLabel) {
                        const shortId = event.session_id.length > 16 ? event.session_id.slice(0, 8) + '...' + event.session_id.slice(-4) : event.session_id;
                        el.arenaSessionLabel.textContent = `SESSION: ${shortId}`;
                    }
                }
                if (event.model && el.arenaModelBadge) {
                    el.arenaModelBadge.textContent = `Model: ${event.model}`;
                }
                break;

            case 'step':
                updateStep(event.step, event.label);
                break;

            case 'tool_call':
                updateStep('tool_call', event.label || `Calling ${event.name}`);
                renderToolInFlight(event.name, event.args);
                appendToolCallCard(assistantBubble, event.name, event.label, event.args);
                break;

            case 'tool_result':
                completeToolCallCard(assistantBubble, event.name, event.result);
                clearToolInFlight();
                break;

            case 'token':
                if (event.token) onToken(event.token);
                break;

            case 'done':
                if (event.session_id) {
                    state.activeSessionId = event.session_id;
                }
                const finalText = event.result || accumulatedText;
                if (finalText) {
                    contentEl.innerHTML = formatMarkdownLike(finalText);
                }
                updateStep('done', state.isAgentMode ? 'Autonomous turn complete.' : 'Conversation response complete.');
                break;

            case 'error':
                contentEl.innerHTML += `<br><span style="color:var(--spartan-crimson)">❌ ${escapeHtml(event.message)}</span>`;
                break;
        }
    }

    // Append Message to Arena Chat
    function appendChatMessage(role, text) {
        const msg = document.createElement('div');
        msg.className = `chat-message ${role}`;
        const avatar = role === 'user' ? '👤' : '⚔️';
        const roleLabel = role === 'user' ? 'COMMANDER // USER' : 'KRATOS VI // AGENT';

        msg.innerHTML = `
            <div class="message-avatar">${avatar}</div>
            <div class="message-body">
                <div class="message-role">${roleLabel}</div>
                <div class="message-content">${formatMarkdownLike(text)}</div>
            </div>
        `;

        el.arenaMessages.appendChild(msg);
        el.arenaMessages.scrollTop = el.arenaMessages.scrollHeight;
        return msg;
    }

    // Append Tool Call Card Inside Assistant Message
    function appendToolCallCard(messageEl, toolName, label, args) {
        const bodyEl = messageEl.querySelector('.message-body');
        const card = document.createElement('div');
        card.className = 'message-tool-card';
        card.id = `tool-card-${toolName}-${Date.now()}`;

        const argsStr = typeof args === 'object' ? JSON.stringify(args, null, 2) : String(args || '{}');

        card.innerHTML = `
            <div class="message-tool-header" onclick="this.nextElementSibling.classList.toggle('d-none')">
                <div class="message-tool-title">
                    <span>🔧</span>
                    <span>${escapeHtml(label || toolName)}</span>
                </div>
                <span class="message-tool-badge">EXECUTING</span>
            </div>
            <div class="message-tool-body">
                <div style="font-size:10px; color:var(--text-dim); text-transform:uppercase;">Arguments:</div>
                <pre style="background:#000; padding:6px; border-radius:4px; color:#93c5fd; overflow-x:auto;"><code>${escapeHtml(argsStr)}</code></pre>
                <div class="tool-result-slot" style="margin-top:4px;"></div>
            </div>
        `;

        bodyEl.appendChild(card);
        el.arenaMessages.scrollTop = el.arenaMessages.scrollHeight;
    }

    function completeToolCallCard(messageEl, toolName, result) {
        const cards = messageEl.querySelectorAll('.message-tool-card');
        if (cards.length === 0) return;
        const lastCard = cards[cards.length - 1];
        const badge = lastCard.querySelector('.message-tool-badge');
        if (badge) {
            badge.textContent = 'COMPLETED';
            badge.style.background = 'rgba(0,255,157,0.2)';
            badge.style.color = 'var(--toxic-green)';
        }

        const slot = lastCard.querySelector('.tool-result-slot');
        if (slot && result) {
            slot.innerHTML = `
                <div style="font-size:10px; color:var(--text-dim); text-transform:uppercase;">Output Preview:</div>
                <pre style="background:#000; padding:6px; border-radius:4px; color:#a7f3d0; overflow-x:auto; max-height:150px;"><code>${escapeHtml(result)}</code></pre>
            `;
        }
        el.arenaMessages.scrollTop = el.arenaMessages.scrollHeight;
    }

    // ==========================================================================
    // RIGHT HUD: STEP TRACKER & TOOL MONITOR
    // ==========================================================================

    function updateStep(stepKey, label) {
        el.currentStepLabel.textContent = label || '';
        el.currentStepTag.textContent = (stepKey || 'ACTIVE').toUpperCase();

        const nodes = [el.nodeReasoning, el.nodePlanning, el.nodeToolCall, el.nodeVerifying];
        nodes.forEach(n => n.classList.remove('active'));

        if (stepKey === 'reasoning') {
            nodes.forEach(n => n.classList.remove('completed'));
            el.nodeReasoning.classList.add('active');
            el.currentStepTag.style.color = 'var(--vice-pink)';
        } else if (stepKey === 'planning') {
            el.nodeReasoning.classList.add('completed');
            el.nodePlanning.classList.add('active');
            el.currentStepTag.style.color = 'var(--vice-orange)';
        } else if (stepKey === 'tool_call') {
            el.nodeReasoning.classList.add('completed');
            el.nodePlanning.classList.add('completed');
            el.nodeToolCall.classList.add('active');
            el.currentStepTag.style.color = 'var(--cyber-cyan)';
        } else if (stepKey === 'verifying') {
            el.nodeReasoning.classList.add('completed');
            el.nodePlanning.classList.add('completed');
            el.nodeToolCall.classList.add('completed');
            el.nodeVerifying.classList.add('active');
            el.currentStepTag.style.color = 'var(--toxic-green)';
        } else if (stepKey === 'done') {
            nodes.forEach(n => n.classList.add('completed'));
            el.currentStepTag.textContent = 'DONE';
            el.currentStepTag.style.color = 'var(--toxic-green)';
        }
    }

    function renderToolInFlight(toolName, args) {
        el.toolInFlightBadge.textContent = 'RUNNING';
        el.toolInFlightBadge.className = 'tool-tag-badge active';

        const argsPreview = typeof args === 'object' ? Object.entries(args).map(([k, v]) => `${k}="${v}"`).join(' ') : String(args || '');

        el.activeToolContent.innerHTML = `
            <div class="tool-live-firing">
                <div class="tool-firing-title">
                    <span>⚡</span>
                    <span>${escapeHtml(toolName)}</span>
                </div>
                <div class="tool-firing-args">${escapeHtml(argsPreview || 'executing...')}</div>
            </div>
        `;
    }

    function clearToolInFlight() {
        el.toolInFlightBadge.textContent = 'STANDBY';
        el.toolInFlightBadge.className = 'tool-tag-badge';
        el.activeToolContent.innerHTML = `
            <div class="no-tool-active">
                <span class="dim-icon">🔧</span>
                <span>No tool currently executing</span>
            </div>
        `;
    }

    function resetHudStandby() {
        el.currentStepTag.textContent = 'IDLE / READY';
        el.currentStepTag.style.color = 'var(--cyber-cyan)';
        el.currentStepLabel.textContent = 'Standing by for next instruction.';
        const nodes = [el.nodeReasoning, el.nodePlanning, el.nodeToolCall, el.nodeVerifying];
        nodes.forEach(n => {
            n.classList.remove('active');
            n.classList.remove('completed');
        });
        clearToolInFlight();
    }

    // ==========================================================================
    // TELEMETRY & TOOLS ARSENAL
    // ==========================================================================

    async function loadTelemetry() {
        try {
            const res = await fetch('/api/telemetry');
            if (!res.ok) return;
            const data = await res.json();
            state.telemetry = data;

            el.telemRuntime.textContent = 'KratosAutonomous';
            el.telemWorkspace.textContent = data.workspace ? data.workspace.split('\\').pop() : 'Kratos_Agent';
            const normalModel = data.normal_mode_model || 'deepseek-web/deepseek-v4-pro';
            el.arenaModelBadge.textContent = state.isAgentMode ? `Model: ${data.model || 'auto'}` : `Model: ${normalModel}`;
            if (data.active_session) {
                el.arenaSessionLabel.textContent = `${data.active_session.title || 'ACTIVE'}`;
            }
        } catch (e) {
            console.error('Failed to load telemetry:', e);
        }
    }

    async function loadTools() {
        try {
            const res = await fetch('/api/tools');
            if (!res.ok) return;
            const tools = await res.json();
            state.tools = tools;
            el.statToolsCount.textContent = tools.length;
            el.arsenalCount.textContent = tools.length;

            el.toolsArsenalList.innerHTML = tools.map(t => {
                const perm = (t.permission || 'read').toLowerCase();
                return `
                    <div class="tool-arsenal-row" title="${escapeHtml(t.description)}">
                        <span class="tool-name-item">🗡️ ${escapeHtml(t.name)}</span>
                        <span class="tool-perm-badge ${escapeHtml(perm)}">${escapeHtml(perm)}</span>
                    </div>
                `;
            }).join('');
        } catch (e) {
            console.error('Failed to load tools:', e);
        }
    }

    // ==========================================================================
    // CLOUDFLARE D1 STATS & SESSIONS
    // ==========================================================================

    async function loadStats() {
        const start = performance.now();
        try {
            const res = await fetch('/api/stats');
            const latency = Math.round(performance.now() - start);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            state.stats = data;

            el.d1ModeText.textContent = data.mode === 'cloudflare_d1' ? 'Cloudflare D1' : 'Local D1 Mirror';
            el.statusPill.className = `status-indicator ${data.mode === 'cloudflare_d1' ? 'online' : 'local'}`;
            el.d1Latency.textContent = `${latency} ms`;
            const dbId = data.database_id || 'kratos_d1.db';
            el.d1DbId.textContent = dbId.length > 18 ? `${dbId.slice(0, 8)}...${dbId.slice(-4)}` : dbId;
            el.d1DbId.title = `Cloudflare D1 Database ID: ${dbId}`;
            el.statSessionsCount.textContent = data.sessions_count || 0;
            el.statTurnsCount.textContent = data.turns_count || 0;
            el.statEventsCount.textContent = data.events_count || 0;
        } catch (err) {
            el.statusPill.className = 'status-indicator error';
            el.d1ModeText.textContent = 'Disconnected';
            el.d1Latency.textContent = 'Err';
        }
    }

    async function loadSessions() {
        try {
            const res = await fetch('/api/sessions');
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            state.sessions = Array.isArray(data) ? data : (data.sessions || []);

            renderSessionList();

            if (state.sessions.length > 0 && !state.activeSessionId) {
                const latestSession = state.sessions[0];
                const latestId = latestSession.session_id || latestSession.id;
                await selectSession(latestId);
                const turnsCount = latestSession.turns_count || (latestSession.turns ? latestSession.turns.length : 0);
                if (turnsCount > 0) {
                    await continueChatFromSession(latestId, true);
                }
            }
        } catch (err) {
            el.sessionList.innerHTML = `<div class="empty-state"><p>Error fetching sessions from D1</p></div>`;
        }
    }

    function renderSessionList(query = '') {
        const filtered = state.sessions.filter(s => {
            if (!query) return true;
            const sid = (s.session_id || s.id || '').toLowerCase();
            const title = (s.title || '').toLowerCase();
            return sid.includes(query) || title.includes(query);
        });

        if (filtered.length === 0) {
            el.sessionList.innerHTML = `<div class="empty-state" style="padding: 20px;"><p style="font-size:12px;">No matching sessions</p></div>`;
            return;
        }

        el.sessionList.innerHTML = filtered.map(s => {
            const sid = s.session_id || s.id;
            const isActive = sid === state.activeSessionId;
            const dateStr = formatDateTime(s.updated_at || s.created_at);
            const turnsCount = s.turns_count || (s.turns ? s.turns.length : 0);

            return `
                <div class="session-item ${isActive ? 'active' : ''}" data-id="${escapeHtml(sid)}" onclick="window.kratosApp.selectSession('${escapeHtml(sid)}')">
                    <div class="session-item-header">
                        <span class="session-item-title" title="${escapeHtml(s.title || sid)}">${escapeHtml(s.title || 'Untitled Session')}</span>
                        <span class="session-item-time">${escapeHtml(dateStr)}</span>
                    </div>
                    <div class="session-item-footer">
                        <span class="tag-mini model">${escapeHtml(s.model || 'auto')}</span>
                        <span class="tag-mini turns">${turnsCount} turns</span>
                        <button class="btn-continue-quick" title="Resume this chat in Arena"
                            onclick="event.stopPropagation(); window.kratosApp.continueChatFromSession('${escapeHtml(sid)}')">
                            ▶ RESUME
                        </button>
                    </div>
                </div>
            `;
        }).join('');
    }

    async function selectSession(sessionId) {
        state.activeSessionId = sessionId;

        const items = el.sessionList.querySelectorAll('.session-item');
        items.forEach(it => it.classList.toggle('active', it.getAttribute('data-id') === sessionId));

        try {
            const [sessionRes, eventsRes] = await Promise.all([
                fetch(`/api/sessions/${sessionId}`),
                fetch(`/api/events/${sessionId}`)
            ]);

            if (sessionRes.ok) {
                state.activeSessionData = await sessionRes.json();
                renderSessionDetail();
            }
            if (eventsRes.ok) {
                const evData = await eventsRes.json();
                state.events = Array.isArray(evData) ? evData : [];
                renderTimeline();
            }
        } catch (e) {
            console.error('Failed to select session:', e);
        }

        // Enable continue chat button when a session is selected
        if (el.btnContinueChat) {
            el.btnContinueChat.disabled = false;
            el.btnContinueChat.style.opacity = '1';
        }
    }

    function renderSessionDetail() {
        const s = state.activeSessionData;
        if (!s) return;

        el.activeSessionTitle.textContent = s.title || s.id;
        el.activeModelBadge.textContent = `Model: ${s.model || 'auto'}`;
        el.activeStatusBadge.textContent = `Status: ${s.last_status || 'ready'}`;
        el.activeUpdatedBadge.textContent = `Updated: ${formatDateTime(s.updated_at)}`;
        el.activeIdBadge.textContent = `ID: ${(s.id || s.session_id || '').slice(0, 8)}...`;

        const turns = s.turns || [];
        el.tabBadgeTurns.textContent = turns.length;
        el.tabBadgeEvents.textContent = state.events.length;

        if (turns.length === 0) {
            el.chatContainer.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">💬</div>
                    <h3>No turns recorded in D1</h3>
                    <p>Switch to the <strong>Agent Arena</strong> tab and send prompts to store conversation turns in D1.</p>
                </div>
            `;
            return;
        }

        el.chatContainer.innerHTML = turns.map((turn, idx) => {
            const toolCalls = turn.tools_used || turn.tool_calls || [];
            return `
                <div class="chat-turn" style="background:var(--bg-surface); border:1px solid var(--border-glass); border-radius:var(--radius-md); padding:16px; margin-bottom:12px;">
                    <div style="display:flex; justify-content:space-between; margin-bottom:8px; font-family:var(--font-mono); font-size:11px; color:var(--spartan-gold);">
                        <span>TURN #${idx + 1}</span>
                        <span style="color:var(--text-dim);">${escapeHtml(turn.timestamp || '')}</span>
                    </div>
                    <div style="font-size:13.5px; color:#ffffff; margin-bottom:10px;">
                        <strong>User:</strong> ${escapeHtml(turn.user || turn.user_query || '')}
                    </div>
                    ${toolCalls.length > 0 ? `
                        <div style="margin:8px 0; padding:8px; background:rgba(0,0,0,0.3); border-radius:4px; font-family:var(--font-mono); font-size:11px; color:var(--cyber-cyan);">
                            🔧 Tools fired: ${toolCalls.map(tc => escapeHtml(tc.name || 'tool')).join(', ')}
                        </div>
                    ` : ''}
                    <div style="font-size:13px; color:var(--text-muted); line-height:1.6;">
                        <strong>Agent:</strong><br>${formatMarkdownLike(turn.agent || turn.agent_reply || '')}
                    </div>
                </div>
            `;
        }).join('');
    }

    // ==========================================================================
    // TRACE TIMELINE & SQL PLAYGROUND
    // ==========================================================================

    function renderTimeline() {
        const filtered = state.events.filter(ev => {
            if (state.traceFilter === 'all') return true;
            const kind = (ev.kind || '').toLowerCase();
            if (state.traceFilter === 'tool') return kind.includes('tool');
            if (state.traceFilter === 'model') return kind.includes('model');
            if (state.traceFilter === 'task') return kind.includes('task') || kind.includes('plan');
            if (state.traceFilter === 'verification') return kind.includes('verify') || kind.includes('test');
            return true;
        });

        el.eventCountDisplay.textContent = `${filtered.length} of ${state.events.length} events from D1`;

        if (filtered.length === 0) {
            el.timelineContainer.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">⚡</div>
                    <h3>No events matching filter</h3>
                </div>
            `;
            return;
        }

        el.timelineContainer.innerHTML = filtered.map((ev, idx) => {
            const kind = ev.kind || 'runtime';
            const category = getEventCategory(kind);
            const icon = getEventIcon(category);
            const timeStr = formatDateTime(ev.timestamp);
            const msg = ev.payload ? (ev.payload.goal || ev.payload.name || ev.payload.title || JSON.stringify(ev.payload)) : (ev.message || '');

            return `
                <div class="timeline-node">
                    <div class="node-icon-box ${category}">${icon}</div>
                    <div class="node-card">
                        <div class="node-card-top">
                            <span class="node-kind ${category}">${escapeHtml(kind)}</span>
                            <span class="node-time">${escapeHtml(timeStr)}</span>
                        </div>
                        <div class="node-message">${escapeHtml(String(msg))}</div>
                        <button class="node-action-btn" onclick="window.kratosApp.inspectEvent(${idx})">Inspect JSON Payload</button>
                    </div>
                </div>
            `;
        }).join('');
    }

    async function executeSql() {
        const sql = el.sqlEditor.value.trim();
        if (!sql) return;

        el.btnRunSql.disabled = true;
        el.sqlResultsMeta.textContent = 'Querying D1...';
        const startTime = performance.now();

        try {
            const res = await fetch('/api/query', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ sql })
            });
            const elapsed = Math.round(performance.now() - startTime);

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.error || `HTTP ${res.status}`);
            }

            const data = await res.json();
            const rows = data.rows || [];
            el.sqlResultsMeta.textContent = `${rows.length} row(s) in ${elapsed} ms (${data.source || 'd1'})`;

            if (rows.length === 0) {
                el.sqlTableContainer.innerHTML = `<div class="sql-empty">Query executed successfully. 0 rows returned.</div>`;
                return;
            }

            const columns = Object.keys(rows[0]);
            const headerHtml = columns.map(c => `<th>${escapeHtml(c)}</th>`).join('');
            const rowsHtml = rows.map(r => {
                const cells = columns.map(c => {
                    const v = r[c];
                    const s = typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v !== null && v !== undefined ? v : 'NULL');
                    return `<td title="${escapeHtml(s)}">${escapeHtml(s)}</td>`;
                }).join('');
                return `<tr>${cells}</tr>`;
            }).join('');

            el.sqlTableContainer.innerHTML = `
                <table class="d1-table">
                    <thead><tr>${headerHtml}</tr></thead>
                    <tbody>${rowsHtml}</tbody>
                </table>
            `;
        } catch (err) {
            el.sqlResultsMeta.textContent = `Error (${Math.round(performance.now() - startTime)} ms)`;
            el.sqlTableContainer.innerHTML = `<div style="padding:20px; color:var(--spartan-crimson); font-family:var(--font-mono); font-size:12px;">❌ ${escapeHtml(err.message)}</div>`;
        } finally {
            el.btnRunSql.disabled = false;
        }
    }

    // ==========================================================================
    // ACTION HELPERS & UTILITIES
    // ==========================================================================

    async function handleCreateNewSession() {
        const title = prompt('Enter new session title:', 'Autonomous Mission');
        if (!title) return;

        try {
            const res = await fetch('/api/sessions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title, model: 'auto' })
            });
            if (res.ok) {
                const s = await res.json();
                await loadSessions();
                await selectSession(s.id || s.session_id);
                switchTab('arenaTab');
            }
        } catch (e) {
            alert('Failed to create session: ' + e.message);
        }
    }

    // ==========================================================================
    // CONTINUE CHAT FROM PREVIOUS SESSION
    // ==========================================================================

    async function continueChatFromSession(sessionId, silent = false) {
        try {
            const res = await fetch(`/api/sessions/${sessionId}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const session = await res.json();

            // Clear arena and restore turns as chat bubbles
            el.arenaMessages.innerHTML = '';

            const turns = session.turns || [];
            if (turns.length === 0) {
                // No prior turns — just switch and set session
                if (el.welcomeCard) el.arenaMessages.appendChild(el.welcomeCard);
            } else {
                // Replay each turn as chat messages (user query + agent response + tools)
                turns.forEach(turn => {
                    const userQuery = turn.user || turn.user_query || turn.query || '';
                    const agentReply = turn.agent || turn.agent_reply || turn.response || turn.assistant || '';
                    const tools = turn.tools_used || turn.tool_calls || [];

                    if (userQuery) {
                        appendChatMessage('user', userQuery);
                    }
                    if (agentReply || tools.length > 0) {
                        const assistantBubble = appendChatMessage('assistant', agentReply);
                        if (tools && tools.length > 0) {
                            tools.forEach(tool => {
                                const toolName = tool.name || 'tool';
                                const toolArgs = tool.arguments || tool.args || {};
                                appendToolCallCard(assistantBubble, toolName, `[tool call] ${toolName}`, toolArgs);
                                completeToolCallCard(assistantBubble, toolName, tool.result || 'executed');
                            });
                        }
                    }
                });
            }

            // Set active session so new messages join the same context
            state.activeSessionId = sessionId;

            // Update header label
            if (el.arenaSessionLabel) {
                const shortId = sessionId.length > 16 ? sessionId.slice(0, 8) + '...' + sessionId.slice(-4) : sessionId;
                el.arenaSessionLabel.textContent = session.title || shortId;
            }

            // Switch to arena tab
            switchTab('arenaTab');

            // Focus input ready for next message
            setTimeout(() => {
                el.arenaInput.focus();
                el.arenaMessages.scrollTop = el.arenaMessages.scrollHeight;
            }, 80);

            if (!silent) {
                showToast(`▶ Resumed: ${session.title || sessionId}`, 'cyan');
            }
        } catch (e) {
            console.error('Failed to continue chat:', e);
            if (!silent) showToast('Failed to load session history', 'error');
        }
    }

    function showToast(message, type = 'cyan') {
        const existing = document.getElementById('kratosToast');
        if (existing) existing.remove();

        const colors = {
            cyan: { bg: 'rgba(0,240,255,0.12)', border: 'rgba(0,240,255,0.5)', text: 'var(--cyber-cyan)' },
            green: { bg: 'rgba(0,255,157,0.12)', border: 'rgba(0,255,157,0.5)', text: 'var(--toxic-green)' },
            error: { bg: 'rgba(255,42,85,0.12)', border: 'rgba(255,42,85,0.5)', text: '#ff8ca3' }
        };
        const c = colors[type] || colors.cyan;

        const toast = document.createElement('div');
        toast.id = 'kratosToast';
        toast.style.cssText = `
            position: fixed;
            bottom: 28px;
            left: 50%;
            transform: translateX(-50%) translateY(60px);
            background: ${c.bg};
            border: 1px solid ${c.border};
            color: ${c.text};
            font-family: var(--font-pixl);
            font-size: 12px;
            letter-spacing: 1.5px;
            padding: 10px 20px;
            border-radius: 6px;
            box-shadow: 0 8px 30px rgba(0,0,0,0.7);
            z-index: 9999;
            transition: transform 0.3s cubic-bezier(0.16,1,0.3,1), opacity 0.3s ease;
            opacity: 0;
            white-space: nowrap;
        `;
        toast.textContent = message;
        document.body.appendChild(toast);

        requestAnimationFrame(() => {
            toast.style.transform = 'translateX(-50%) translateY(0)';
            toast.style.opacity = '1';
        });

        setTimeout(() => {
            toast.style.transform = 'translateX(-50%) translateY(60px)';
            toast.style.opacity = '0';
            setTimeout(() => toast.remove(), 350);
        }, 3000);
    }

    async function handleDeleteActiveSession() {
        if (!state.activeSessionId) return;
        if (!confirm(`Delete session ${state.activeSessionId} from Cloudflare D1?`)) return;

        try {
            await fetch(`/api/sessions/${state.activeSessionId}`, { method: 'DELETE' });
            state.activeSessionId = null;
            await loadSessions();
            await loadStats();
        } catch (e) {
            alert('Failed to delete: ' + e.message);
        }
    }

    function inspectEvent(idx) {
        const ev = state.events[idx];
        if (!ev) return;
        el.modalEventTitle.textContent = `Event: ${ev.kind || 'trace'}`;
        el.modalEventJson.textContent = JSON.stringify(ev, null, 2);
        el.payloadModal.classList.add('open');
    }

    function getEventCategory(kind) {
        const k = (kind || '').toLowerCase();
        if (k.includes('tool')) return 'tool';
        if (k.includes('model')) return 'model';
        if (k.includes('task') || k.includes('plan')) return 'task';
        if (k.includes('verify') || k.includes('test')) return 'verification';
        return 'general';
    }

    function getEventIcon(cat) {
        switch (cat) {
            case 'tool': return '🔧';
            case 'model': return '🧠';
            case 'task': return '📋';
            case 'verification': return '🛡️';
            default: return '⚡';
        }
    }

    function formatDateTime(iso) {
        if (!iso) return '--';
        try {
            const d = new Date(iso);
            if (isNaN(d.getTime())) return iso;
            return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' ' + d.toLocaleDateString([], { month: 'short', day: 'numeric' });
        } catch (_) {
            return iso;
        }
    }

    function escapeHtml(str) {
        if (str === null || str === undefined) return '';
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
    }

    function renderCodeBlock(lang, codeText) {
        let cleanLang = (lang || '').trim().toLowerCase();
        // Common language alias normalization
        const aliasMap = {
            'js': 'javascript',
            'ts': 'typescript',
            'py': 'python',
            'rs': 'rust',
            'rb': 'ruby',
            'sh': 'bash',
            'shell': 'bash',
            'yml': 'yaml',
            'cs': 'csharp',
            'c++': 'cpp'
        };
        if (aliasMap[cleanLang]) {
            cleanLang = aliasMap[cleanLang];
        }

        let highlighted = '';
        let displayLang = cleanLang ? cleanLang.toUpperCase() : 'CODE';

        if (window.hljs) {
            try {
                if (cleanLang && window.hljs.getLanguage(cleanLang)) {
                    highlighted = window.hljs.highlight(codeText, { language: cleanLang, ignoreIllegals: true }).value;
                } else {
                    const autoRes = window.hljs.highlightAuto(codeText);
                    highlighted = autoRes.value;
                    if (!cleanLang && autoRes.language) {
                        displayLang = autoRes.language.toUpperCase();
                    }
                }
            } catch (err) {
                highlighted = escapeHtml(codeText);
            }
        } else {
            highlighted = escapeHtml(codeText);
        }

        const langClass = cleanLang ? `language-${escapeHtml(cleanLang.toLowerCase())}` : '';

        return `
            <div class="code-dialog-box">
                <div class="code-dialog-header">
                    <span class="code-lang-badge">${escapeHtml(displayLang)}</span>
                    <button class="btn-copy-code" onclick="window.kratosApp.copyCode(this)">COPY</button>
                </div>
                <pre><code class="hljs ${langClass}">${highlighted}</code></pre>
            </div>
        `;
    }

    function formatInlineMarkdown(text) {
        if (!text) return '';
        const escaped = escapeHtml(text);
        return escaped
            .replace(/\*\*\*(.*?)\*\*\*/g, '<strong><em>$1</em></strong>')
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.*?)\*/g, '<em>$1</em>')
            .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');
    }

    function renderMarkdownTable(lines) {
        if (!lines || lines.length < 2) return '';
        const parseRow = (line) => {
            const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '');
            return trimmed.split('|').map(cell => cell.trim());
        };
        const headerCells = parseRow(lines[0]);
        const isAlignRow = /^[\s|:-]+$/.test(lines[1]);
        const dataRows = isAlignRow ? lines.slice(2) : lines.slice(1);

        let html = '<div class="table-responsive"><table class="markdown-table"><thead><tr>';
        headerCells.forEach(cell => {
            html += `<th>${formatInlineMarkdown(cell)}</th>`;
        });
        html += '</tr></thead><tbody>';

        dataRows.forEach(rowStr => {
            if (!rowStr.trim()) return;
            const cells = parseRow(rowStr);
            html += '<tr>';
            cells.forEach(cell => {
                html += `<td>${formatInlineMarkdown(cell)}</td>`;
            });
            html += '</tr>';
        });

        html += '</tbody></table></div>';
        return html;
    }

    function formatMarkdownLike(str) {
        if (!str) return '';

        // Match complete or in-progress code blocks
        const codeBlockRegex = /```([a-zA-Z0-9_\-\+]*)\r?\n([\s\S]*?)(?:```|$)/g;
        let segments = [];
        let lastIndex = 0;
        let match;

        while ((match = codeBlockRegex.exec(str)) !== null) {
            const beforeCode = str.substring(lastIndex, match.index);
            if (beforeCode) {
                segments.push({ type: 'text', content: beforeCode });
            }
            segments.push({
                type: 'code',
                lang: match[1],
                code: match[2]
            });
            lastIndex = match.index + match[0].length;
            if (!match[0].endsWith('```') && lastIndex === str.length) {
                break;
            }
        }

        if (lastIndex < str.length) {
            segments.push({ type: 'text', content: str.substring(lastIndex) });
        }

        let result = '';
        segments.forEach(seg => {
            if (seg.type === 'code') {
                result += renderCodeBlock(seg.lang, seg.code);
            } else {
                result += renderTextMarkdown(seg.content);
            }
        });

        return result;
    }

    function renderTextMarkdown(text) {
        if (!text) return '';
        const lines = text.split(/\r?\n/);
        let out = '';
        let i = 0;

        while (i < lines.length) {
            const line = lines[i];
            const trimmed = line.trim();

            // Horizontal Rule (---, ***, ___)
            if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
                out += '<hr class="markdown-hr">';
                i++;
                continue;
            }

            // Headings (###### down to #)
            const hMatch = trimmed.match(/^(#{1,6})\s+(.*)$/);
            if (hMatch) {
                const level = hMatch[1].length;
                const hText = formatInlineMarkdown(hMatch[2]);
                out += `<h${level} class="md-heading md-h${level}">${hText}</h${level}>`;
                i++;
                continue;
            }

            // Markdown Table detection: line with | and next line with |:--:|
            if (trimmed.startsWith('|') && i + 1 < lines.length && /^[\s|:-]+$/.test(lines[i + 1].trim())) {
                const tableLines = [];
                while (i < lines.length && lines[i].trim().startsWith('|')) {
                    tableLines.push(lines[i]);
                    i++;
                }
                out += renderMarkdownTable(tableLines);
                continue;
            }

            // Blockquote
            if (trimmed.startsWith('>')) {
                const bqText = formatInlineMarkdown(trimmed.replace(/^>\s?/, ''));
                out += `<blockquote class="md-blockquote">${bqText}</blockquote>`;
                i++;
                continue;
            }

            // Unordered list
            if (/^[-*+]\s+/.test(trimmed)) {
                let listHtml = '<ul class="md-list">';
                while (i < lines.length && /^[-*+]\s+/.test(lines[i].trim())) {
                    const itemText = lines[i].trim().replace(/^[-*+]\s+/, '');
                    listHtml += `<li>${formatInlineMarkdown(itemText)}</li>`;
                    i++;
                }
                listHtml += '</ul>';
                out += listHtml;
                continue;
            }

            // Ordered list
            if (/^\d+\.\s+/.test(trimmed)) {
                let listHtml = '<ol class="md-list md-list-ordered">';
                while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
                    const itemText = lines[i].trim().replace(/^\d+\.\s+/, '');
                    listHtml += `<li>${formatInlineMarkdown(itemText)}</li>`;
                    i++;
                }
                listHtml += '</ol>';
                out += listHtml;
                continue;
            }

            // Empty line
            if (!trimmed) {
                out += '<div class="md-spacer"></div>';
                i++;
                continue;
            }

            // Regular paragraph line
            out += `<p class="md-paragraph">${formatInlineMarkdown(line)}</p>`;
            i++;
        }

        return out;
    }

    function copyCode(btn) {
        const box = btn.closest('.code-dialog-box');
        if (!box) return;
        const codeEl = box.querySelector('pre code');
        if (!codeEl) return;
        const text = codeEl.innerText;
        navigator.clipboard.writeText(text).then(() => {
            const orig = btn.textContent;
            btn.textContent = 'COPIED!';
            btn.style.color = 'var(--toxic-green)';
            btn.style.borderColor = 'var(--toxic-green)';
            setTimeout(() => {
                btn.textContent = orig;
                btn.style.color = '';
                btn.style.borderColor = '';
            }, 2000);
        }).catch(err => {
            console.error('Clipboard copy failed:', err);
        });
    }

    // Expose global controller
    window.kratosApp = {
        selectSession,
        inspectEvent,
        copyCode,
        continueChatFromSession,
        showToast
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
