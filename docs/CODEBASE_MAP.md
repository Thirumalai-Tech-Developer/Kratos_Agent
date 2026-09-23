# Kratos Agent — Comprehensive Codebase Map & File Index

This document provides complete, exhaustive architectural documentation of every single useful file in the **Kratos Agent** repository. Each entry details the file's path, subsystem, primary responsibilities, key classes and functions, and how it interacts with the rest of the system.

---

## Table of Contents

1. [Entry Points & CLI](#1-entry-points--cli)
2. [Core Execution Engine (`src/kratos_agent/core/`)](#2-core-execution-engine)
3. [Performance & Fast Path Engine (`src/kratos_agent/performance/`)](#3-performance--fast-path-engine)
4. [Event Pipeline (`src/kratos_agent/events/`)](#4-event-pipeline)
5. [Output & Voice Pipeline (`src/kratos_agent/output/`)](#5-output--voice-pipeline)
6. [Shell Abstraction Layer (`src/kratos_agent/system/shell/`)](#6-shell-abstraction-layer)
7. [Brain LLM Client & Gateway (`src/kratos_agent/brain/`)](#7-brain-llm-client--gateway)
8. [Live Multimodal Session (`src/kratos_agent/live/`)](#8-live-multimodal-session)
9. [Computer Control & Automation (`src/kratos_agent/computer/`)](#9-computer-control--automation)
10. [CCS Low-Level Cross-Platform Driver (`src/kratos_agent/ccs/`)](#10-ccs-low-level-cross-platform-driver)
11. [Memory Engine V2 (`src/kratos_agent/memory/`)](#11-memory-engine-v2)
12. [Tools & Utility Modules (`src/kratos_agent/utils/` & `tools/`)](#12-tools--utility-modules)
13. [Terminal UI & Web Server (`src/kratos_agent/tui/` & `web/`)](#13-terminal-ui--web-server)
14. [Configuration, Documentation & Setup](#14-configuration-documentation--setup)

---

## 1. Entry Points & CLI

### [`cli.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/cli.py)
- **Subsystem**: User Interface & CLI Runner
- **Purpose**: The interactive command-line interface for Kratos. Implements Rich terminal rendering, interactive REPL loop, slash commands (`/voice`, `/vision`, `/live`, `/mode`, `/model`, `/skill`, `/bg-run`), background task management, and session resumption.
- **Key Exports**: `main()`, `run_interactive_cli()`, `handle_slash_command()`, `display_banner()`.
- **Connections**: Initializes `AgentLoop` from `core/agent_loop.py`, connects to `LiveSession` from `live/session.py`, and hooks into `output/terminal.py` for clean user messaging.

### [`main.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/main.py)
- **Subsystem**: Agent Runtime Entry
- **Purpose**: Programmatic initialization and startup point for the Kratos autonomous agent. Parses environment configuration, loads tools and skills, configures LLM providers, and executes single-shot or daemon tasks.
- **Key Exports**: `KratosAgent`, `run_agent()`, `initialize_agent_environment()`.
- **Connections**: Instantiates `AgentLoop`, `ToolRegistry`, `MemoryManager`, and `PromptBuilder`.

### [`__init__.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/__init__.py)
- **Subsystem**: Package Definition
- **Purpose**: Declares the `kratos_agent` package and exports package-level version metadata and public classes.

### [`__main__.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/__main__.py)
- **Subsystem**: Module Executable
- **Purpose**: Enables running Kratos as a Python module (`python -m kratos_agent`), forwarding execution directly to `cli.py:main`.

---

## 2. Core Execution Engine

Located in [`src/kratos_agent/core/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core).

### [`agent_loop.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/agent_loop.py)
- **Purpose**: The central autonomous execution loop. Manages iterative cycles: observing the current state, assembling context, calling the LLM via `provider_runtime.py`, executing structured actions, parsing tool results, enforcing safety constraints, and checking completion conditions.
- **Key Exports**: `AgentLoop`, `StepResult`, `LoopStatus`.
- **Connections**: Drives `tool_runtime.py`, `context_pipeline.py`, `planner.py`, and emits events to `events/bus.py`.

### [`planner.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/planner.py)
- **Purpose**: High-level goal planning and dynamic replanning. Breaks down complex, multi-step requests into sequential sub-tasks. Detects step failure and adjusts plans without losing progress.
- **Key Exports**: `Planner`, `PlanStep`, `ExecutionPlan`.
- **Connections**: Used by `agent_loop.py` for `COMPLEX_TASK` requests routed from `performance/router.py`.

### [`prompt_builder.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/prompt_builder.py)
- **Purpose**: 5-layer modular system prompt builder (`CORE_PROMPT`, `TASK_CONTEXT`, `RELEVANT_MEMORY`, `AVAILABLE_TOOLS`, `CURRENT_STATE`). Implements the compact, high-speed system prompt (§54) with zero prompt bloat (0.07ms build time).
- **Key Exports**: `PromptBuilder`, `CORE_PROMPT_V2`.
- **Connections**: Assembled by `context_pipeline.py` before each LLM turn.

### [`prompt_library.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/prompt_library.py)
- **Purpose**: Central catalog of specialized system prompts, task templates, verification prompts, and persona configurations.
- **Key Exports**: `PROMPT_TEMPLATES`, `get_specialized_prompt()`.

### [`structured_action.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/structured_action.py)
- **Purpose**: Pydantic models for structured agent actions and execution state transitions. Guarantees type-safe communication between LLM output and tool execution.
- **Key Exports**: `AgentAction`, `TaskResult`, `ActionStateMachine`, `CachedPlan`, `ActionStatus`.
- **Connections**: Validates actions emitted by `agent_loop.py` and enforces states (`READY` → `OBSERVING` → `PLANNING` → `EXECUTING` → `VERIFYING` → `SUCCESS`).

### [`tool_runtime.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/tool_runtime.py)
- **Purpose**: Dynamic tool registry and schema manager. Implements category-based filtering (`GENERAL`, `CODE`, `FILES`, `SYSTEM`, `BROWSER`, `COMPUTER`, `MEMORY`) to expose only necessary tools to the model, reducing prompt tokens by ~90%.
- **Key Exports**: `ToolRegistry`, `ToolCategory`, `RegisteredTool`, `ToolResult`.
- **Connections**: Feeds schemas to `context_pipeline.py` and dispatches execution to `utils/tools.py` and `computer/tools/`.

### [`context_pipeline.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/context_pipeline.py)
- **Purpose**: Assembles the complete context payload for model requests. Manages token budgeting, deterministic tool-result pruning, history compaction, and credential redaction.
- **Key Exports**: `ContextPipeline`, `ContextPayload`, `assemble_context()`.

### [`instruction_engine.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/instruction_engine.py)
- **Purpose**: Composable instruction engine managing discrete `InstructionModule` objects (system rules, user preferences, security constraints) rather than concatenated strings.
- **Key Exports**: `InstructionEngine`, `InstructionModule`.

### [`provider_runtime.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/provider_runtime.py)
- **Purpose**: Provider-neutral LLM runtime interface. Connects to Brain Gateway, DeepSeek, OpenAI, Anthropic, Gemini, Groq, and local models using standard message envelopes.
- **Key Exports**: `ModelAdapter`, `ProviderRuntime`, `LLMResponse`.

### [`cognitive_memory.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/cognitive_memory.py)
- **Purpose**: Connects core agent operations with long-term and working memory. Translates execution outcomes into episodic facts and retrieves procedural patterns.
- **Key Exports**: `CognitiveMemoryBridge`, `extract_learning_from_turn()`.

### [`memory.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/memory.py)
- **Purpose**: Core memory abstraction for session history, persistent KV storage, memory summarization, and vector indexing.
- **Key Exports**: `MemoryStore`, `MemoryEntry`.

### [`project_memory.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/project_memory.py)
- **Purpose**: Tracks repository and project-specific knowledge (build commands, coding conventions, known bugs, architecture patterns) stored in `KRATOS.md`.
- **Key Exports**: `ProjectMemoryTracker`, `load_project_knowledge()`.

### [`d1_client.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/d1_client.py) & [`d1_schema.sql`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/d1_schema.sql)
- **Purpose**: Cloudflare D1 integration client providing global, distributed persistent memory, session synchronization, and audit logging across devices.
- **Key Exports**: `D1Client`, `D1SessionSync`.

### [`approval_mode.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/approval_mode.py)
- **Purpose**: Human-in-the-loop permission gateway. Supports `suggest`, `auto-edit`, and `full-auto` execution modes. Intercepts dangerous operations (file deletion, network access, shell commands) for user confirmation.
- **Key Exports**: `ApprovalGate`, `ApprovalMode`, `check_tool_permission()`.

### [`background_runner.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/background_runner.py)
- **Purpose**: Runs long-running tasks asynchronously in background threads or processes. Provides status polling, output buffering, and cancellation.
- **Key Exports**: `BackgroundRunner`, `BackgroundTask`.

### [`command_lint.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/command_lint.py)
- **Purpose**: Static safety analysis and linting for shell commands prior to execution. Flags destructive commands (`rm -rf`, `format`, `del /f /s /q`) and recommends safer alternatives.
- **Key Exports**: `CommandLinter`, `LintResult`, `lint_shell_command()`.

### [`compactor.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/compactor.py)
- **Purpose**: Conversation history compaction and token-budget optimizer. Summarizes older conversation turns into structured milestones while preserving recent messages and active plan states.
- **Key Exports**: `HistoryCompactor`, `compact_history()`.

### [`dispute.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/dispute.py)
- **Purpose**: Detects hallucinations and disputes between what the LLM claimed it did and actual tool execution outcomes. Enforces evidence verification.
- **Key Exports**: `DisputeDetector`, `EvidenceValidator`.

### [`event_bus.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/event_bus.py), [`event_adapter.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/event_adapter.py), [`event_store.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/event_store.py)
- **Purpose**: Legacy internal event tracking and JSONL replay logging (`.kratos/sessions/<id>/events.jsonl`).
- **Key Exports**: `EventBus`, `EventStore`, `log_event()`.

### [`evidence.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/evidence.py)
- **Purpose**: Defines evidence contracts for task verification. Guarantees that an agent cannot mark a task as completed without concrete tool-verified evidence (e.g., file exists, test exited 0, page URL changed).
- **Key Exports**: `EvidenceContract`, `verify_evidence()`.

### [`git_tools.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/git_tools.py)
- **Purpose**: Direct Git operations (status, diff, commit, branch, log) via direct subprocess calls rather than shell invocations.
- **Key Exports**: `GitTools`, `get_git_status()`, `get_git_diff()`.

### [`hooks.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/hooks.py)
- **Purpose**: Extensible lifecycle hook registry (`pre_task`, `post_task`, `pre_tool`, `post_tool`, `on_error`).
- **Key Exports**: `HookRegistry`, `register_hook()`, `trigger_hooks()`.

### [`latency_tracker.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/latency_tracker.py)
- **Purpose**: Granular execution timing per turn and subsystem (LLM inference, tool execution, perception, context assembly).
- **Key Exports**: `LatencyTracker`, `TurnMetrics`.

### [`mcp_runtime.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/mcp_runtime.py)
- **Purpose**: Model Context Protocol (MCP) client. Connects to external MCP servers configured in `.kratos/mcp.json` via stdio or SSE transports, registering dynamic tools (`mcp__<server>__<tool>`).
- **Key Exports**: `MCPClient`, `MCPRuntime`, `load_mcp_servers()`.

### [`reloader.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/reloader.py)
- **Purpose**: Development helper for dynamic hot-reloading of Python modules and tools without restarting the CLI session.
- **Key Exports**: `HotReloader`.

### [`runtime_contracts.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/runtime_contracts.py)
- **Purpose**: Abstract base classes and interfaces for agent runtimes, tool providers, and execution runners.
- **Key Exports**: `AgentRuntimeProtocol`, `ToolProviderProtocol`.

### [`skills.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/skills.py)
- **Purpose**: Skill discovery, parsing, and execution. Reads `SKILL.md` instruction files from workspace and global customization folders.
- **Key Exports**: `SkillManager`, `Skill`, `discover_skills()`.

### [`subagents.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/subagents.py)
- **Purpose**: Spawns isolated child agent instances for parallel sub-tasks with independent histories and bounded token budgets.
- **Key Exports**: `SubagentManager`, `SubagentTask`, `run_subagent()`.

### [`task_manager.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/task_manager.py)
- **Purpose**: Manages multi-task queues, task prioritization, status updates, and cancellation propagation.
- **Key Exports**: `TaskManager`, `TaskState`, `TaskStatus`.

### [`verification_manager.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/verification_manager.py)
- **Purpose**: Completion gatekeeper ensuring no success response is generated until programmatic verification succeeds.
- **Key Exports**: `VerificationManager`, `VerificationResult`.

### [`workspace_tracker.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/workspace_tracker.py)
- **Purpose**: Tracks active workspace root, open files, active editor cursor positions, and recently modified files.
- **Key Exports**: `WorkspaceTracker`, `WorkspaceState`.

---

## 3. Performance & Fast Path Engine

Located in [`src/kratos_agent/performance/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/performance).

### [`router.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/performance/router.py)
- **Purpose**: High-speed intent classifier and fast-path router. Evaluates requests in sub-millisecond time, classifying into `CHAT`, `CODE`, `TOOL`, `COMPUTER_USE`, `BROWSER`, `MEMORY_QUERY`, or `COMPLEX_TASK`. Enables simple tasks to execute directly without planning, memory lookup, or repo inspection.
- **Key Exports**: `RequestRouter`, `RequestCategory`, `RouteDecision`, `get_request_router()`.
- **Connections**: Called at the beginning of `agent_loop.py` and `cli.py` to route user turns.

### [`profiler.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/performance/profiler.py)
- **Purpose**: Turn latency profiler. Measures routing, memory retrieval, observation, LLM call, and tool execution times, emitting structured `[PERF]` metrics.
- **Key Exports**: `Profiler`, `get_profiler()`.

---

## 4. Event Pipeline

Located in [`src/kratos_agent/events/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/events).

### [`models.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/events/models.py)
- **Purpose**: Data models for agent events. Defines `EventType` (`TASK_RECEIVED`, `TASK_STARTED`, `PLAN_CREATED`, `ACTION_STARTED`, `ACTION_COMPLETED`, `ACTION_FAILED`, `MILESTONE`, `VERIFICATION_STARTED`, `VERIFICATION_COMPLETED`, `TASK_COMPLETED`, `TASK_FAILED`, `DEBUG`, `TOOL_OUTPUT`) and `AgentEvent`.
- **Key Exports**: `EventType`, `AgentEvent`.

### [`bus.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/events/bus.py)
- **Purpose**: Thread-safe, asynchronous event bus. Dispatches events from the core agent and tools to terminal renderers, voice buffers, debug panels, and event logs.
- **Key Exports**: `EventBus`, `get_event_bus()`.

### [`filters.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/events/filters.py)
- **Purpose**: Event predicate functions separating user-visible events from internal implementation details.
- **Key Exports**: `is_user_visible()`, `is_internal()`, `is_milestone()`.

---

## 5. Output & Voice Pipeline

Located in [`src/kratos_agent/output/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/output).

### [`user_output.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/output/user_output.py)
- **Purpose**: Output filter enforcing three display modes (`NORMAL`, `DEBUG`, `SILENT`). Hides tool outputs, action starts, and debug noise in normal mode.
- **Key Exports**: `UserOutputFilter`, `OutputMode`.

### [`voice.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/output/voice.py)
- **Purpose**: Voice sentence buffering and TTS serialization. Eliminates token-fragment speech by buffering until sentence boundaries (`.`, `!`, `?`, `\n`) with `MIN_TTS_CHARS = 35` and `MAX_TTS_CHARS = 240`. Houses `TTSQueue` with dedicated worker and instant cancellation (`cancel_current()`).
- **Key Exports**: `VoiceBuffer`, `TTSQueue`.

### [`aggregator.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/output/aggregator.py)
- **Purpose**: Milestone aggregator. Strips banned repetitive progress phrases (`"I am currently..."`, `"I am running..."`, `"I'm starting..."`, `"I am confirming..."`) and deduplicates repeated progress notifications.
- **Key Exports**: `OutputAggregator`, `BANNED_PREFIXES`, `MILESTONES`.

### [`terminal.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/output/terminal.py)
- **Purpose**: Terminal renderer formatting clean milestone messages (`⚡ Kratos: <milestone>`) and completion notifications (`⚡ Kratos: ✓ Done`).
- **Key Exports**: `TerminalRenderer`.

---

## 6. Shell Abstraction Layer

Located in [`src/kratos_agent/system/shell/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/system/shell).

### [`base.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/system/shell/base.py)
- **Purpose**: Core shell data models (`ShellInfo`, `CommandResult`).
- **Key Exports**: `ShellInfo`, `CommandResult`.

### [`detect.py`](file:///c:/Users/thratos_Agent/src/kratos_agent/system/shell/detect.py)
- **Purpose**: Automatic environment shell detection. Identifies Windows PowerShell 5.1, PowerShell Core (`pwsh`), CMD, and Bash, recording supported operators.
- **Key Exports**: `detect_shell()`.

### [`renderer.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/system/shell/renderer.py)
- **Purpose**: Translates shell commands for target shells. Converts `&&` into `; if ($?) { ... }` and `||` into `; if (-not $?) { ... }` for PowerShell 5.1. Produces direct subprocess argv lists to avoid shell execution.
- **Key Exports**: `render_powershell_script()`, `render_command_argv()`.

### [`output_parser.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/system/shell/output_parser.py)
- **Purpose**: PowerShell output parser. Strips `#< CLIXML` tags, removes `<Obj S="progress"...>` progress records, decodes XML escape sequences (`_x000D__x000A_`), and extracts clean error text.
- **Key Exports**: `normalize_command_output()`, `strip_clixml_progress()`.

---

## 7. Brain LLM Client & Gateway

Located in [`src/kratos_agent/brain/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/brain).

### [`client.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/brain/client.py)
- **Purpose**: HTTP and WebSocket client communicating with the centralized Brain LLM gateway (`http://127.0.0.1:20128` / OmniRoute). Supports streaming and tool-call envelopes.
- **Key Exports**: `BrainClient`, `BrainMessage`, `BrainStreamChunk`.

### [`chat_model.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/brain/chat_model.py)
- **Purpose**: LangChain / OpenAI-compatible chat model wrapper over the Brain gateway.
- **Key Exports**: `ChatBrainModel`.

### [`config.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/brain/config.py)
- **Purpose**: Configuration models for gateway endpoints, model names, fallback providers, and timeouts.
- **Key Exports**: `BrainConfig`, `load_brain_config()`.

### [`brain.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/brain/brain.py)
- **Purpose**: High-level initialization and health check manager for the Brain connection.
- **Key Exports**: `BrainSession`, `init_brain()`.

---

## 8. Live Multimodal Session

Located in [`src/kratos_agent/live/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/live).

### [`session.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/live/session.py)
- **Purpose**: Gemini Live bidirectional WebSocket session. Streams audio input and video/screen frames to Gemini Live in real-time, receives audio responses, and connects tool execution back to the agent loop.
- **Key Exports**: `LiveSession` and the Gemini Live connection/receive lifecycle. Extended-thinking sessions use non-blocking tool declarations and `interaction_status` to determine true idle state.

### [`microphone.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/live/microphone.py)
- **Purpose**: Low-level microphone capture using `sounddevice` first with PyAudio fallback. Handles 16kHz PCM capture, VAD, audio buffering, device selection, and Windows endpoint mute diagnostics.
- **Key Exports**: `MicrophoneListener`, `get_input_devices()`, `get_microphone_health()`.

### [`speaker.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/live/speaker.py)
- **Purpose**: Audio output playback using PyAudio. Streams 24kHz PCM audio from Gemini Live / TTS to system speakers with smooth buffering.
- **Key Exports**: `SpeakerOutput`.

### [`audio.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/live/audio.py)
- **Purpose**: Common audio utilities, PCM encoding/decoding, and loudness normalization.
- **Key Exports**: `pcm_to_wav()`, `resample_audio()`.

### [`screen.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/live/screen.py)
- **Purpose**: Fast desktop screen grabber (using `mss` or Windows Graphics Capture). Compresses frames to JPEG for streaming to Gemini Live vision.
- **Key Exports**: `ScreenCaptureStream`.

### [`camera.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/live/camera.py)
- **Purpose**: OpenCV webcam capture stream for live physical environment observation.
- **Key Exports**: `CameraCaptureStream`.

### [`vision.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/live/vision.py)
- **Purpose**: Vision mode coordinator (`camera`, `screen`, `both`, `off`). Dispatches active frame sources to the Live session.
- **Key Exports**: `VisionMode`, `VisionCoordinator`.

### [`avatar.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/live/avatar.py)
- **Purpose**: Animated ASCII / Unicode terminal avatar reflecting live state (`LISTENING`, `THINKING`, `SPEAKING`, `EXECUTING`, `IDLE`).
- **Key Exports**: `LiveAvatar`, `AvatarState`.

### [`router.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/live/router.py)
- **Purpose**: Voice intent router. Classifies user speech to decide whether Gemini Live should answer directly via voice or dispatch an autonomous background task to Kratos.
- **Key Exports**: `VoiceIntentRouter`, `IntentClassification`.

### [`runtime.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/live/runtime.py) & [`bridge.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/live/bridge.py)
- **Purpose**: Owns the Live lifecycle in a background asyncio thread and bridges Gemini perception/actions to the existing Master/Slave execution supervisor.
- **Key Exports**: `LiveRuntime`, `get_live_runtime()`, `KratosBridge`.

### [`events.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/live/events.py)
- **Purpose**: Live session event models (`SpeechStarted`, `SpeechEnded`, `TurnComplete`, `ToolCallReceived`).
- **Key Exports**: `LiveEvent`, `LiveEventType`.

### [`config.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/live/config.py)
- **Purpose**: Configuration parameters for Gemini Live (voice model, sample rates, chunk sizes, vision FPS).
- **Key Exports**: `LiveConfig`.

### [`narration.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/live/narration.py)
- **Purpose**: Formats concise, natural speech feedback for live tasks without narration bloat.
- **Key Exports**: `SpeechNarrator`.

---

## 9. Computer Control & Automation

Located in [`src/kratos_agent/computer/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer).

### [`manager.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/manager.py)
- **Purpose**: Central computer-use orchestrator. Implements `_execution_lock = asyncio.Lock()` ensuring that only one computer-control task operates the desktop at a time, preventing race conditions.
- **Key Exports**: `ComputerManager`, `get_computer_manager()`.

### [`observer.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/observer.py)
- **Purpose**: High-speed desktop state observer. Gathers active window title, process name, window geometry, accessibility controls, and open browser URL.
- **Key Exports**: `ComputerObserver`, `ObserverSnapshot`.

### [`state_cache.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/state_cache.py)
- **Purpose**: Hash-based `StateCache`. Computes a sub-millisecond hash of active window, title, and URL; returns cached observations in 0.009ms if the environment hasn't changed.
- **Key Exports**: `StateCache`, `DesktopStateHash`.

### [`state.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/state.py)
- **Purpose**: Data models representing complete desktop snapshots (`DesktopState`, `WindowState`, `UIElementState`).
- **Key Exports**: `DesktopState`, `WindowState`.

### [`executor.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/executor.py)
- **Purpose**: Safe action execution engine. Translates high-level actions (`click_element`, `type_text`, `launch_app`, `navigate_browser`) into backend-specific calls.
- **Key Exports**: `ComputerExecutor`, `ExecutionOutcome`.

### [`capabilities.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/capabilities.py)
- **Purpose**: System capability cache. Detects installed backends (Playwright, Chrome, UIA, X11, Wayland) once and caches them to avoid repeated dependency checks.
- **Key Exports**: `CapabilityRegistry`, `get_capabilities()`.

### [`permissions.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/permissions.py)
- **Purpose**: Verifies that the agent has necessary OS-level accessibility and screen recording permissions.
- **Key Exports**: `PermissionChecker`, `ensure_permissions()`.

### [`planner.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/planner.py)
- **Purpose**: Specialized UI navigation planner for multi-window workflows.
- **Key Exports**: `ComputerPlanner`.

### [`recovery.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/recovery.py)
- **Purpose**: UI failure recovery. Dismisses unexpected modals, closes crashed windows, and refocuses target apps.
- **Key Exports**: `UIRecoveryEngine`.

### [`verifier.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/verifier.py)
- **Purpose**: Programmatic UI verification. Confirms window presence, URL match, or DOM state before signaling success.
- **Key Exports**: `ComputerVerifier`.

### `browser/` Subsystem
- [`browser/selector.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/browser/selector.py): `BrowserBackendSelector` selecting `EXISTING_SESSION` or `PLAYWRIGHT` before GUI automation, completely avoiding Selenium/ChromeDriver for standard tasks.
- [`browser/playwright.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/browser/playwright.py): Playwright browser automation driver managing tabs, navigation, DOM queries, and video playback verification.
- [`browser/manager.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/browser/manager.py): Lifecycle manager for browser processes and persistent browser contexts.

### `apps/` Subsystem
- [`apps/launcher.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/apps/launcher.py): Launches desktop applications using OS protocols and Start Menu / PATH indexing.
- [`apps/windows.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/apps/windows.py): Window geometry, minimization, maximization, and focus switching.
- [`apps/processes.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/apps/processes.py): Process listing, PID lookup, and termination.
- [`apps/focus.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/apps/focus.py): Reliable window foreground focus enforcement.

### `gui/` Subsystem
- [`gui/resolver.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/gui/resolver.py): Resolves textual element queries ("Submit button", "Search box") to accessibility nodes or screen coordinates.
- [`gui/selectors.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/gui/selectors.py): CSS and XPath-style selector parser for desktop accessibility trees.
- [`gui/inspector.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/gui/inspector.py): Fast accessibility tree crawler extracting interactive elements.
- [`gui/actions.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/gui/actions.py): Dispatches mouse clicks, double clicks, drags, and key sequences.
- [`gui/models.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/gui/models.py): GUI element representations (`BoundingBox`, `ControlPattern`).

### `filesystem/` Subsystem
- [`filesystem/files.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/filesystem/files.py): Desktop file operations (open with default app, reveal in explorer).
- [`filesystem/clipboard.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/filesystem/clipboard.py): System clipboard read/write without simulated hotkeys.

### `vision/` Subsystem
- [`vision/detector.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/vision/detector.py): Visual UI element detection and OCR for non-accessible canvas/game apps.
- [`vision/grounding.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/vision/grounding.py): Maps text labels to pixel bounding boxes.
- [`vision/interpreter.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/vision/interpreter.py): Screen diff analyzer detecting changes after clicks.

### `tools/` Subsystem
- [`tools/computer_tools.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/tools/computer_tools.py): Agent tool wrappers for computer control actions.
- [`tools/browser_tools.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/tools/browser_tools.py): Direct browser navigation and inspection tools.
- [`tools/gui_tools.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/tools/gui_tools.py): GUI-specific interaction tools.
- [`tools/system_tools.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/tools/system_tools.py): System volume, screen resolution, and lock tools.

---

## 10. CCS Low-Level Cross-Platform Driver

Located in [`src/kratos_agent/ccs/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs).

### [`base.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/base.py)
- **Purpose**: Base hardware driver interface. Defines platform-agnostic contracts for screen capture, mouse input, keyboard input, accessibility queries, and process management.
- **Key Exports**: `BasePlatformDriver`, `ScreenRegion`, `KeyAction`.

### [`assertions.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/assertions.py)
- **Purpose**: Low-level post-action assertion library (verifies focus changed, window appeared, text was entered).
- **Key Exports**: `assert_window_active()`, `assert_element_exists()`.

### [`doctor.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/doctor.py)
- **Purpose**: Environment diagnostics tool (`kratos doctor`). Inspects OS version, display server (X11/Wayland), audio devices, DPI scaling, and permission status.
- **Key Exports**: `run_ccs_diagnostics()`, `DiagnosticReport`.

### [`windows.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/windows.py) & [`linux.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/linux.py)
- **Purpose**: Platform-specific implementations of `BasePlatformDriver` using Win32 / ctypes on Windows and Xlib / AT-SPI on Linux.
- **Key Exports**: `WindowsDriver`, `LinuxDriver`.

### [`discovery.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/discovery.py)
- **Purpose**: Auto-detects running applications, installed browsers, and system tools across platforms.
- **Key Exports**: `discover_installed_apps()`.

### [`safety_ops.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/safety_ops.py)
- **Purpose**: Emergency failsafes (e.g., mouse moved to screen corner triggers instant abort).
- **Key Exports**: `check_failsafe()`.

### [`tasks.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/tasks.py)
- **Purpose**: High-level atomic automation tasks (e.g., "type into focused control", "click button with label").
- **Key Exports**: `execute_ccs_task()`.

### `input/` Subsystem
- [`input/windows.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/input/windows.py): Low-level Win32 `SendInput` mouse and keyboard synthesizer supporting Unicode and scan codes.
- [`input/hotkey.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/input/hotkey.py): Hotkey parser and simulator (e.g. `ctrl+shift+p`).
- [`input/interlock.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/input/interlock.py): Input interlock preventing simulated inputs while user is physically typing/moving mouse.
- [`input/keys.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/input/keys.py): Virtual key codes and scan code mapping tables.

### `perception/` Subsystem
- [`perception/a11y_windows.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/perception/a11y_windows.py): Direct Windows UI Automation (UIA) COM wrapper.
- [`perception/blockers.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/perception/blockers.py): Automatic detection and handling of modal popups, UAC dialogs, and alert blockers.
- [`perception/screenshot.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/perception/screenshot.py): Sub-millisecond screenshot grabber.
- [`perception/screen_diff.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/perception/screen_diff.py): Frame differencing to isolate regions of the screen that changed.
- [`perception/ocr.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/perception/ocr.py): Windows Media OCR / Tesseract wrapper.
- [`perception/grounding.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/perception/grounding.py): Grounding perception coordinates to display scale factors.
- [`perception/cache.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/perception/cache.py): Memory cache for visual perception results.

### `browser/cdp.py` & `system/elevation.py`
- [`browser/cdp.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/browser/cdp.py): Chrome DevTools Protocol (CDP) direct WebSocket connection to active browser instances.
- [`system/elevation.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/system/elevation.py): Manages running commands with elevated administrator privileges when required.

---

## 11. Memory Engine V2

Located in [`src/kratos_agent/memory/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/memory).

### [`models.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/memory/models.py)
- **Purpose**: Data models for the 6 cognitive memory layers (`WORKING`, `EPISODIC`, `SEMANTIC`, `PROCEDURAL`, `APPLICATION`, `ERROR`) and 7 scopes (`TASK`, `SESSION`, `PROJECT`, `APPLICATION`, `USER`, `GLOBAL`, `WORKFLOW`).
- **Key Exports**: `MemoryItem`, `MemoryLayer`, `MemoryScope`.

### [`manager.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/memory/manager.py)
- **Purpose**: Memory coordinator. Manages sub-millisecond hot-cache lookups (0.08ms), multi-factor ranking, and asynchronous background consolidation. Provides compact context (2–4 bullet points) to the prompt builder.
- **Key Exports**: `MemoryManager`, `get_memory_manager()`.

### [`ranking.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/memory/ranking.py)
- **Purpose**: Multi-factor hybrid ranking algorithm combining similarity (30%), task relevance (25%), importance (15%), confidence (15%), recency (5%), frequency (5%), and context match (5%).
- **Key Exports**: `rank_memories()`.

### [`decay.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/memory/decay.py)
- **Purpose**: Applies layer-specific temporal decay and boosts utility scores on verified execution success.
- **Key Exports**: `apply_decay()`, `reinforce_memory()`.

### [`consolidation.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/memory/consolidation.py)
- **Purpose**: Background deduplication and semantic clustering of related facts into consolidated knowledge.
- **Key Exports**: `consolidate_memories()`.

### [`store.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/memory/store.py)
- **Purpose**: SQLite and in-memory storage engine for memory items, embedding vectors, and metadata indices.
- **Key Exports**: `MemoryStore`.

### Specialized Memory Layers
- [`working.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/memory/working.py): Working memory tracking active variables, current goal, and recent step results.
- [`procedural.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/memory/procedural.py): Procedural memory storing multi-step workflow recipes and keyboard shortcuts.
- [`application.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/memory/application.py): App-specific facts (e.g. Chrome flags, VS Code commands).
- [`errors.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/memory/errors.py): Error memory storing past failure signatures and verified recovery actions.

---

## 12. Tools & Utility Modules

Located in [`src/kratos_agent/utils/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/utils) and [`src/kratos_agent/tools/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/tools).

### [`utils/tools.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/utils/tools.py)
- **Purpose**: Primary tool implementations exposed to Kratos (`read_file`, `write_file`, `edit_file`, `list_directory`, `grep_search`, `run_terminal_command`, `web_search`). Uses the shell abstraction layer and output normalizer.
- **Key Exports**: Tool execution functions, `execute_tool()`.

### [`utils/computer_tools.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/utils/computer_tools.py)
- **Purpose**: Desktop automation tools (`click_element`, `mouse_click`, `keyboard_type`, `take_screenshot`, `press_hotkey`, `focus_window`).
- **Key Exports**: Computer tool dispatchers.

### [`utils/shell_quote.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/utils/shell_quote.py)
- **Purpose**: Cross-platform argument escaping for Windows CMD, PowerShell, and Unix shells.
- **Key Exports**: `quote_arg()`, `quote_command()`.

### [`utils/tool_creator.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/utils/tool_creator.py)
- **Purpose**: Allows Kratos to dynamically generate and register new Python tools at runtime.
- **Key Exports**: `create_dynamic_tool()`.

### [`utils/step_tracker.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/utils/step_tracker.py)
- **Purpose**: Step counting and turn budget enforcement.
- **Key Exports**: `StepTracker`.

### [`utils/sync_tools.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/utils/sync_tools.py)
- **Purpose**: Synchronizes tool declarations between Python code and `tools_list.json`.

### [`utils/tools_list.json`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/utils/tools_list.json)
- **Purpose**: Static JSON schema catalog of all built-in tools.

### [`tools/d1_setup.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/tools/d1_setup.py)
- **Purpose**: Setup script initializing Cloudflare D1 databases and schema tables.

---

## 13. Terminal UI & Web Server

Located in [`src/kratos_agent/tui/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/tui) and [`src/kratos_agent/web/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/web).

### Terminal UI (`src/kratos_agent/tui/`)
- [`live_renderer.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/tui/live_renderer.py): Rich live display split into main interaction area, thought box, and status bar.
- [`debug_panel.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/tui/debug_panel.py): Collapsible debug panel showing real-time latency, tool results, and memory hits.
- [`status_bar.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/tui/status_bar.py): Bottom status bar displaying model name, mode, voice/vision state, and token usage.
- [`completion_view.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/tui/completion_view.py): Formats final response with evidence summaries.
- [`stream_printer.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/tui/stream_printer.py): Smooth streaming token printer with syntax highlighting.
- [`events.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/tui/events.py): UI event definitions.

### Web Server & UI (`src/kratos_agent/web/`)
- [`server.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/web/server.py): FastAPI & WebSocket server exposing Kratos as a browser-based web application (`/`, `/ws`, `/api/task`).
- [`index.html`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/web/index.html): Modern web interface for Kratos with live chat, voice controls, and vision viewports.
- [`highlighter.js`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/web/highlighter.js): Client-side code syntax highlighter.

---

## 14. Configuration, Documentation & Setup

### Project Configuration
- [`pyproject.toml`](file:///c:/Users/thiru/Documents/Kratos_Agent/pyproject.toml): Project metadata, dependencies (`rich`, `pydantic`, `fastapi`, `pyaudio`, `mss`, `playwright`), and CLI script entrypoint (`kratos = "kratos_agent.cli:main"`).
- [`.env`](file:///c:/Users/thiru/Documents/Kratos_Agent/.env): Environment variables (API keys, Brain Gateway URL, model overrides, Cloudflare D1 tokens).

### Documentation Files
- [`docs/architecture.md`](file:///c:/Users/thiru/Documents/Kratos_Agent/docs/architecture.md): High-level runtime architecture and request contract specification.
- [`docs/COMPUTER_USE.md`](file:///c:/Users/thiru/Documents/Kratos_Agent/docs/COMPUTER_USE.md): Architecture guide for computer-use and autonomous desktop operations.
- [`docs/GUI_AUTOMATION.md`](file:///c:/Users/thiru/Documents/Kratos_Agent/docs/GUI_AUTOMATION.md): Guide for GUI accessibility tree navigation and element resolution.
- [`docs/cloudflare_d1_setup.md`](file:///c:/Users/thiru/Documents/Kratos_Agent/docs/cloudflare_d1_setup.md): Setup instructions for Cloudflare D1 persistent memory.
- [`docs/SECURITY.md`](file:///c:/Users/thiru/Documents/Kratos_Agent/docs/SECURITY.md): Security guidelines, sandboxing, and approval policies.


### Current Gemini Live contract
The `live/` package targets `gemini-3.8-live-extended-thinking`. Live function declarations are asynchronous/non-blocking, and the receive loop uses `interaction_status=IDLE` as the authoritative end-of-interaction signal. `turnComplete` is treated as an utterance boundary only for the extended-thinking model. Component errors are stored per subsystem so microphone or capture failures cannot overwrite Gemini connection diagnostics.
