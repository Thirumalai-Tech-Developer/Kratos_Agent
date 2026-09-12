# Frontend Reference

The frontend is a React 19/Vite application under `frontend/src`. `App.jsx` owns API state and workflow orchestration; components are presentational/action surfaces.

## `App.jsx`

`App` tracks navigation (`activeTab`, HUD), server data (`stats`, `telemetry`, `tools`, `sessions`, active session, events, SQL results/errors), chat (`messages`, prompt, execution, current step, active tool), and modal/auth state.

Functions and flows:

- `refreshAll()`: concurrently calls stats, telemetry, tools, sessions, and events loaders.
- `fetchStats`, `fetchTelemetry`, `fetchTools`, `fetchSessions`, `fetchSessionDetail(id)`, `fetchEvents(sessionId=null)`: fetch corresponding `/api` endpoints and update state.
- `handleToggleAgentMode()`: turns agent mode off or opens authentication.
- `handleAuthenticate(password)`: POSTs the password, supports the local `kratos` fallback, and updates auth state/errors.
- `parseThinkTags(rawContent, currentReasoning='')`: removes complete or in-progress `<think>` blocks and returns `{reasoning, content, isThinking}`.
- `handleSendPrompt(customPrompt=null)`: POSTs `/api/chat`, reads either JSON or SSE, accumulates tokens/reasoning, maps steps/tool calls to HUD state, finalizes the assistant message, and refreshes persisted data.
- session handlers select, resume, delete, and create sessions; SQL execution posts `{query}` and updates results/errors; event inspection opens `PayloadModal`.

## Components and props

- `AgentArena({messages, inputPrompt, setInputPrompt, onSend, onClear, isExecuting, currentStep, activeTool, isAgentMode, modelName, sessionId})`: chat stream, keyboard submit, reasoning accordion, Markdown replies, and prompt input. Internal `ReasoningAccordion` expands live/finished reasoning.
- `AgentHud({currentStep, activeTool, tools, onRefreshTools, isOpen, onClose, telemetry})`: four-stage progress meter, active tool monitor, searchable tool list, and responsive drawer.
- `Navbar({stats, telemetry, isAgentMode, onToggleAgentMode, onRefresh, onNewSession, onOpenTechSpecs, isHudOpen, onToggleHud, activeTab, onSelectTab})`: responsive navigation, D1 stats, agent switch, new session, and mobile menu.
- `RecruiterStrip({onSelectPrompt})`: shortcut prompts for common review/build/security workflows.
- `SessionsExplorer({sessions, activeSessionId, activeSessionData, onSelectSession, onResumeSession, onDeleteSession, isLoading})`: filterable D1 session list and stored turn view.
- `TraceReplay({events, onInspectPayload, isLoading})`: filters events into all/tool/model/task/verification categories and opens raw payload inspection.
- `SqlPlayground({onExecuteQuery, results, isLoading, error})`: preset/read query editor, Ctrl+Enter execution, errors, and dynamic result table.

## Markdown and modals

`MarkdownRenderer({content, isStreaming})` implements lightweight Markdown without a third-party parser. `escapeHtml` prevents raw HTML injection in inline/text output; `highlightCode` maps aliases and calls `window.hljs` when available; `CodeDialogBox` copies code; `formatInlineMarkdown`, `renderMarkdownTable`, and `renderTextMarkdown` handle emphasis, inline code, headings, tables, blockquotes, lists, code fences, and streaming cursor state.

`AgentAuthModal({isOpen,onClose,onAuthenticate,error})` owns password input/visibility. `TechSpecsModal({isOpen,onClose})` displays architecture capabilities. `PayloadModal({isOpen,onClose,event})` parses and formats `payload_json`, with clipboard copy state.

## Styling and assets

- `index.css`: global Tailwind/theme imports, font-face declarations, neon palette, glass panels, scrollbar and animation utilities.
- `App.css`: application-specific layout and component styles.
- `main.jsx`: mounts `App` into the root element and imports CSS.
- `index.html`: Vite HTML shell and frontend asset bootstrap.
- `public/highlighter.js` and `public/highlighter.json`: vendored Highlight.js runtime/language data used by `MarkdownRenderer`.
- `public/fonts/`: local font assets used by the visual theme.

## Frontend configuration

`vite.config.js` enables React and Tailwind plugins, writes production output to `dist`, runs the dev server on 5173, and proxies `/api` to the local Python server at 7860. `frontend/package.json` defines `dev`, `build`, `lint`, and `preview` scripts.
