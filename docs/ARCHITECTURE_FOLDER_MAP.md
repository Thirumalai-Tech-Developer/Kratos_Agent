# Kratos Agent — Exhaustive Folder & File Architecture Catalog

This document provides a comprehensive, folder-by-folder, subfolder-by-subfolder, and file-by-file architectural analysis of the **Kratos Agent** codebase. Every single file is documented with its path, purpose, defined classes/functions, use cases, inputs/outputs, and inter-file architectural connections.

---

## Table of Contents

1. [Root & Entry Points](#1-root--entry-points)
2. [`src/kratos_agent/brain/` (LLM Gateway)](#2-srckratos_agentbrain)
3. [`src/kratos_agent/core/` (Core Agent Engine)](#3-srckratos_agentcore)
   - [3.1 Core Harness & Plugins (`src/kratos_agent/core/harness/`)](#31-core-harness--plugins)
4. [`src/kratos_agent/performance/` (Routing & Profiling)](#4-srckratos_agentperformance)
5. [`src/kratos_agent/events/` (Event Bus Pipeline)](#5-srckratos_agentevents)
6. [`src/kratos_agent/output/` (Terminal, Voice & User Filtering)](#6-srckratos_agentoutput)
7. [`src/kratos_agent/system/shell/` (Shell Abstraction)](#7-srckratos_agentsystemshell)
8. [`src/kratos_agent/live/` (Multimodal Realtime Session)](#8-srckratos_agentlive)
9. [`src/kratos_agent/computer/` (Computer Control Engine)](#9-srckratos_agentcomputer)
   - [9.1 `apps/` (Application & Window Focus)](#91-apps)
   - [9.2 `browser/` (Playwright & Target Manager)](#92-browser)
   - [9.3 `filesystem/` (Files & Clipboard)](#93-filesystem)
   - [9.4 `gui/` (GUI Accessibility & Input Backends)](#94-gui)
   - [9.5 `tools/` (Computer Tool Wrappers)](#95-tools)
   - [9.6 `vision/` (Screen Vision & Grounding)](#96-vision)
10. [`src/kratos_agent/ccs/` (Cross-Platform Driver Subsystem)](#10-srckratos_agentccs)
    - [10.1 `browser/` (CDP Protocol Bridge)](#101-browser)
    - [10.2 `input/` (Input Injection Drivers)](#102-input)
    - [10.3 `perception/` (Screen & Blocker Perception)](#103-perception)
    - [10.4 `system/` (System Elevation)](#104-system)
11. [`src/kratos_agent/memory/` (Layered Cognitive Memory V2)](#11-srckratos_agentmemory)
12. [`src/kratos_agent/utils/` & `tools/` (Built-in Tools & Helpers)](#12-srckratos_agentutils--tools)
13. [`src/kratos_agent/tui/` & `web/` (Terminal UI & Web Server)](#13-srckratos_agenttui--web)
14. [`docs/` (Architecture & Specifications)](#14-docs)
15. [Root Workspace Files & Build Scripts](#15-root-workspace-files--build-scripts)
16. [`documentation/` (Reference Manuals)](#16-documentation)
17. [`frontend/` (Vite + React Cloudflare Pages Web App)](#17-frontend)
18. [`functions/` (Cloudflare Pages API Functions)](#18-functions)
19. [`tests/` (Test Suites & Benchmarks)](#19-tests)

---

## 1. Root & Entry Points

### [`cli.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/cli.py)
- **Folder**: `src/kratos_agent/`
- **Purpose**: Interactive CLI entry point and REPL loop for terminal interaction.
- **Classes & Functions**:
  - `main()`: Top-level entry point parsing CLI flags (`--cli`, `--web`, `--daemon`, `--port`, `--model`).
  - `run_interactive_cli()`: The interactive terminal loop managing user turns, prompt input, Rich formatting, slash commands, and status display.
  - `handle_slash_command(cmd, args)`: Dispatches interactive commands (`/voice`, `/vision`, `/live`, `/mode`, `/model`, `/skill`, `/bg-run`, `/help`).
  - `display_banner()`: Renders the startup ASCII/Rich banner showing active model, mode, tools count, skills count, and status indicators.
- **Use Case**: Primary interface when running `kratos` or `uv run kratos --cli`.
- **Connections**: Initializes `AgentLoop` (`core/agent_loop.py`), starts `LiveSession` (`live/session.py`), and uses `TerminalRenderer` (`output/terminal.py`).

### [`main.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/main.py)
- **Folder**: `src/kratos_agent/`
- **Purpose**: Autonomous agent orchestration engine and programmatic runtime initialization.
- **Classes & Functions**:
  - `KratosAgent`: Orchestrates tool registry, memory manager, prompt builder, and execution loops.
  - `run_agent(query, agent_mode)`: Autonomous single-shot execution of a user prompt without interactive prompts.
  - `initialize_agent_environment()`: Loads environment variables, validates LLM gateway connectivity, and registers built-in tools.
- **Use Case**: Programmatic and background task execution called from `cli.py`, `live/bridge.py`, and test suites.
- **Connections**: Glues `core/agent_loop.py`, `core/tool_runtime.py`, `core/prompt_builder.py`, and `memory/manager.py`.

### [`__init__.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/__init__.py)
- **Folder**: `src/kratos_agent/`
- **Purpose**: Package declaration and version metadata.
- **Use Case**: Marks `kratos_agent` as a Python package and exports `__version__ = "0.2.0"`.

### [`__main__.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/__main__.py)
- **Folder**: `src/kratos_agent/`
- **Purpose**: Executable module wrapper.
- **Use Case**: Allows running Kratos via `python -m kratos_agent`.
- **Connections**: Directly calls `kratos_agent.cli:main()`.

---

## 2. `src/kratos_agent/brain/`

Centralized Brain LLM Gateway connection and model adapters.

### [`brain/__init__.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/brain/__init__.py)
- **Purpose**: Exports Brain client, config, and chat model symbols.

### [`brain/brain.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/brain/brain.py)
- **Purpose**: High-level Brain session lifecycle manager.
- **Classes & Functions**:
  - `BrainSession`: Manages connection state, ping/heartbeat checks, and authentication tokens to the Brain gateway.
  - `init_brain(config)`: Initializes the global Brain connection.
- **Use Case**: Ensures the LLM gateway is reachable before starting agent loops.

### [`brain/client.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/brain/client.py)
- **Purpose**: Low-level HTTP and WebSocket transport client for the Brain gateway.
- **Classes & Functions**:
  - `BrainClient`: Handles synchronous and asynchronous requests to `http://127.0.0.1:20128/v1/chat/completions`.
  - `send_chat(messages, tools, stream)`: Sends chat payloads and yields streaming response tokens or tool call fragments.
  - `health_check()`: Verifies gateway endpoint availability with sub-50ms timeout.
- **Use Case**: Communicates with OmniRoute / DeepSeek-V4 / Gemini gateways.
- **Connections**: Used by `brain/chat_model.py` and `core/provider_runtime.py`.

### [`brain/chat_model.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/brain/chat_model.py)
- **Purpose**: LangChain / OpenAI-compatible chat model interface wrapping `BrainClient`.
- **Classes & Functions**:
  - `ChatBrainModel`: Implements `invoke()`, `stream()`, `bind_tools()`.
  - `_convert_messages_to_payload()`: Translates standard message formats to gateway envelopes.
- **Use Case**: Plugs the Brain gateway into any tool-calling or reasoning loop expecting an OpenAI-like model.

### [`brain/config.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/brain/config.py)
- **Purpose**: Configuration dataclasses and environment variable loader for Brain settings.
- **Classes & Functions**:
  - `BrainConfig`: Holds `endpoint_url`, `api_key`, `model_name`, `timeout`, and `temperature`.
  - `load_brain_config()`: Reads from `.env` or system environment.

### [`brain/fetch_model.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/brain/fetch_model.py)
- **Purpose**: Helper for querying available model IDs from the gateway `/v1/models` endpoint.

---

## 3. `src/kratos_agent/core/`

The core cognitive, planning, context assembly, and execution loop of Kratos.

### [`core/__init__.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/__init__.py)
- **Purpose**: Package declaration for core agent algorithms.

### [`core/agent_loop.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/agent_loop.py)
- **Purpose**: The central multi-turn autonomous execution loop.
- **Classes & Functions**:
  - `AgentLoop`: Manages step execution, observation, tool calls, and completion gates.
  - `run_turn(query, history)`: Executes a single turn, classifying route, evaluating actions, checking approvals, and verifying state.
  - `_execute_tool_wave(calls)`: Safely groups and runs non-conflicting tool calls in parallel waves.
  - `format_tool_action_label(name, args)`: Formats clean lowercase milestone labels for the user.
- **Use Case**: Core runtime driving all agent interactions.
- **Connections**: Dispatches tools via `tool_runtime.py`, builds prompts via `prompt_builder.py`, routes via `performance/router.py`.

### [`core/planner.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/planner.py)
- **Purpose**: Dynamic multi-step task planning and intent classification.
- **Classes & Functions**:
  - `IntentKind`: Enum (`CHAT`, `QUESTION`, `CODING_TASK`, `FILE_TASK`, `COMPLEX_AGENT_TASK`).
  - `classify_intent(query)`: Classifies requests into plan-requiring tasks vs. immediate conversation.
  - `Planner`: Formulates sequential task steps (`TaskItem`) and dynamically replans when steps fail.
- **Use Case**: Used for `COMPLEX_TASK` requests that cannot be solved in a single fast path.

### [`core/prompt_builder.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/prompt_builder.py)
- **Purpose**: High-speed 5-layer system prompt builder with zero bloat (0.07ms construction latency).
- **Classes & Functions**:
  - `PromptBuilder`: Assembles `CORE_PROMPT`, `TASK_CONTEXT`, `RELEVANT_MEMORY`, `AVAILABLE_TOOLS`, and `CURRENT_STATE`.
  - `CORE_PROMPT_V2`: The concise, rule-oriented prompt (§54) enforcing direct execution, shell awareness, and truthful verification.
- **Use Case**: Produces the exact model instructions before each LLM turn.

### [`core/prompt_library.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/prompt_library.py)
- **Purpose**: Catalog of specialized personas, role descriptions, and task-specific instruction templates.

### [`core/structured_action.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/structured_action.py)
- **Purpose**: Type-safe action protocol and state machine for agent execution.
- **Classes & Functions**:
  - `AgentAction`: Represents an action (`type`, `tool`, `arguments`, `reason`, `expected_result`).
  - `TaskResult`: Standard terminal response format (`success`, `status`, `summary`, `evidence`, `error`).
  - `ActionStateMachine`: Enforces state transitions (`READY` → `OBSERVING` → `PLANNING` → `EXECUTING` → `VERIFYING` → `SUCCESS`).
  - `CachedPlan`: Caches active plan progress step-by-step.

### [`core/tool_runtime.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/tool_runtime.py)
- **Purpose**: Dynamic tool registry and category-based schema filtering.
- **Classes & Functions**:
  - `ToolCategory`: Enum (`GENERAL`, `CODE`, `FILES`, `SYSTEM`, `BROWSER`, `COMPUTER`, `MEMORY`).
  - `ToolRegistry`: Manages tool registrations, argument validation, capability checks, and filtering.
  - `get_tools(categories, context)`: Filters 181 tools down to the 5–15 relevant tools for the current turn, saving ~90% token overhead.

### [`core/context_pipeline.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/context_pipeline.py)
- **Purpose**: Token budgeting, history compaction, and deterministic tool-result pruning.
- **Classes & Functions**:
  - `ContextPipeline`: Assembles final model request objects, estimates token counts, and redacts credentials.

### [`core/instruction_engine.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/instruction_engine.py)
- **Purpose**: Composable instruction engine managing discrete `InstructionModule` components.

### [`core/provider_runtime.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/provider_runtime.py)
- **Purpose**: Multi-provider LLM runtime adapter.
- **Classes & Functions**:
  - `ModelAdapter`: Abstract base class for model providers.
  - `OmniRouteAdapter`: Implementation connecting to OmniRoute / Brain gateway.

### [`core/cognitive_memory.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/cognitive_memory.py)
- **Purpose**: Bridges agent loop step results with long-term episodic and procedural memory.

### [`core/memory.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/memory.py)
- **Purpose**: Base memory storage abstraction for session persistence, search, and recall.

### [`core/project_memory.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/project_memory.py)
- **Purpose**: Reads, updates, and tracks project-level conventions and facts stored in `KRATOS.md`.

### [`core/d1_client.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/d1_client.py) & [`core/d1_schema.sql`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/d1_schema.sql)
- **Purpose**: Cloudflare D1 distributed database client for cross-device persistent memory and history sync.

### [`core/approval_mode.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/approval_mode.py)
- **Purpose**: Human-in-the-loop permission gateway (`suggest`, `auto-edit`, `full-auto`).

### [`core/background_runner.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/background_runner.py)
- **Purpose**: Asynchronous task runner for non-blocking background operations.

### [`core/command_lint.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/command_lint.py)
- **Purpose**: Static safety validator for shell commands to prevent destructive executions.

### [`core/compactor.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/compactor.py)
- **Purpose**: Summarizes older conversation turns to keep active context within token limits.

### [`core/dispute.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/dispute.py)
- **Purpose**: Validates model claims against actual tool results to catch hallucinations.

### [`core/event_adapter.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/event_adapter.py), [`core/event_bus.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/event_bus.py), [`core/event_store.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/event_store.py)
- **Purpose**: Internal event recording and `.kratos/sessions/<id>/events.jsonl` persistence.

### [`core/evidence.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/evidence.py)
- **Purpose**: Evidence contract enforcing that completion requires observable proof.

### [`core/git_tools.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/git_tools.py)
- **Purpose**: Native Python subprocess wrappers for Git operations (status, diff, branch, commit).

### [`core/hooks.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/hooks.py)
- **Purpose**: Lifecycle hooks (`pre_task`, `post_task`, `pre_tool`, `post_tool`, `on_error`).

### [`core/latency_tracker.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/latency_tracker.py)
- **Purpose**: Subsystem latency telemetry recording turn timing.

### [`core/mcp_runtime.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/mcp_runtime.py)
- **Purpose**: Model Context Protocol (MCP) dynamic client connecting to external stdio/SSE servers.

### [`core/reloader.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/reloader.py)
- **Purpose**: Dynamic hot-reloading of agent modules during development.

### [`core/runtime_contracts.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/runtime_contracts.py)
- **Purpose**: Protocol and interface definitions for agent runtimes and tools.

### [`core/skills.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/skills.py)
- **Purpose**: Discovers and parses `SKILL.md` instruction files from workspace and user folders.

### [`core/subagents.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/subagents.py)
- **Purpose**: Spawns isolated child agent instances with independent context windows for parallel sub-tasks.

### [`core/task_deduplicator.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/task_deduplicator.py)
- **Purpose**: Normalizes task strings and suppresses duplicate tasks arriving within 3 seconds (§30).
- **Classes & Functions**:
  - `TaskDeduplicator`: Implements `normalize_task()`, `is_duplicate()`, `clear()`.

### [`core/task_manager.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/task_manager.py)
- **Purpose**: Task lifecycle, task status models, and plan execution queues.

### [`core/verification_manager.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/verification_manager.py)
- **Purpose**: Gatekeeper preventing task completion without verified proof.

### [`core/workspace_tracker.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/workspace_tracker.py)
- **Purpose**: Tracks active workspace files, cursor positions, and modified file sets.

---

### 3.1 Core Harness & Plugins

Located in [`src/kratos_agent/core/harness/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/harness).

- [`harness/__init__.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/harness/__init__.py): Harness exports.
- [`harness/kernel.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/harness/kernel.py): Agent harness kernel managing plugin lifecycles and pipeline interception.
- [`harness/plugin.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/harness/plugin.py): Abstract base class `HarnessPlugin` for modular runtime extensions.
- [`harness/presets.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/harness/presets.py): Predefined configurations and tool presets for different operational profiles.
- **Plugins (`harness/plugins/`)**:
  - [`audit_plugin.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/harness/plugins/audit_plugin.py): Audits all tool calls and writes structured security logs.
  - [`creator_plugin.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/harness/plugins/creator_plugin.py): Allows the agent to self-create tools and skills.
  - [`deepseek_model_plugin.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/harness/plugins/deepseek_model_plugin.py): DeepSeek-specific parameter and reasoning tag parser.
  - [`headroom_plugin.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/harness/plugins/headroom_plugin.py): Dynamic context headroom manager enforcing token budget margins.
  - [`memory_plugin.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/harness/plugins/memory_plugin.py): Intercepts turns to auto-inject relevant memories and save new facts.
  - [`tools_plugin.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/harness/plugins/tools_plugin.py): Integrates dynamic tool discovery into the harness.

---

## 4. `src/kratos_agent/performance/`

High-speed intent classification, fast-path routing, and turn latency profiling.

### [`performance/__init__.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/performance/__init__.py)
- **Purpose**: Performance module exports.

### [`performance/router.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/performance/router.py)
- **Purpose**: High-speed `RequestRouter` for classifying user tasks and enabling fast paths (§17, §18, §19).
- **Classes & Functions**:
  - `RequestCategory`: Enum (`CHAT`, `CODE`, `TOOL`, `FILE_OPERATION`, `COMPUTER_USE`, `BROWSER`, `MEMORY_QUERY`, `COMPLEX_TASK`).
  - `RouteDecision`: Dataclass containing category, `is_fast_path`, target tool categories, planning requirement, memory requirement, observation requirement.
  - `RequestRouter.classify(request)`: Sub-millisecond classifier using regex and pattern heuristics to bypass planning for simple queries ("open youtube", "what is 2+2", "git status").
- **Use Case**: Called at the beginning of each turn to select direct path vs. complex planner.

### [`performance/profiler.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/performance/profiler.py)
- **Purpose**: Granular turn latency profiler.
- **Classes & Functions**:
  - `Profiler`: Context manager `measure(segment)` recording timing for `route`, `memory`, `observe`, `llm`, `tool`.
  - `log_turn()`: Outputs `[PERF]` metrics matching performance budgets.

---

## 5. `src/kratos_agent/events/`

Structured agent event bus decoupling internal operations from user-visible output (§2, §3, §4).

### [`events/__init__.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/events/__init__.py)
- **Purpose**: Exports event models and the global event bus.

### [`events/models.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/events/models.py)
- **Purpose**: Event data models.
- **Classes & Functions**:
  - `EventType`: Enum (`TASK_RECEIVED`, `TASK_STARTED`, `PLAN_CREATED`, `ACTION_STARTED`, `ACTION_COMPLETED`, `ACTION_FAILED`, `MILESTONE`, `VERIFICATION_STARTED`, `VERIFICATION_COMPLETED`, `TASK_COMPLETED`, `TASK_FAILED`, `DEBUG`, `TOOL_OUTPUT`).
  - `AgentEvent`: Structured dataclass (`type`, `task_id`, `message`, `data`, `timestamp`, `level`).

### [`events/bus.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/events/bus.py)
- **Purpose**: Thread-safe asynchronous event dispatcher.
- **Classes & Functions**:
  - `EventBus`: Implements `emit(event)`, `subscribe(handler, event_types)`, `unsubscribe()`.
  - `get_event_bus()`: Singleton provider.

### [`events/filters.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/events/filters.py)
- **Purpose**: Event filtering predicates.
- **Classes & Functions**:
  - `is_user_visible(event)`: Returns True only for `TASK_RECEIVED`, `TASK_STARTED`, `MILESTONE`, `TASK_COMPLETED`, `TASK_FAILED`.
  - `is_internal(event)`: Returns True for `ACTION_STARTED`, `TOOL_OUTPUT`, `DEBUG`, `VERIFICATION_STARTED`.
  - `is_milestone(event)`: Identifies meaningful progress checkpoints.

---

## 6. `src/kratos_agent/output/`

Formatting, terminal rendering, milestone aggregation, and voice sentence buffering (§4, §5, §7–§14).

### [`output/__init__.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/output/__init__.py)
- **Purpose**: Output module exports.

### [`output/user_output.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/output/user_output.py)
- **Purpose**: User output filtering enforcing three display modes (§4, §5).
- **Classes & Functions**:
  - `OutputMode`: Enum (`NORMAL`, `DEBUG`, `SILENT`).
  - `UserOutputFilter`: `should_display(event)`, `should_speak(event)`. Ensures internal reasoning and tool outputs are never displayed or spoken in normal mode.

### [`output/voice.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/output/voice.py)
- **Purpose**: Voice sentence buffer and serialized TTS queue (§7–§14).
- **Classes & Functions**:
  - `VoiceBuffer`: Buffers streaming tokens until sentence delimiters (`.`, `!`, `?`, `\n`) with `MIN_TTS_CHARS = 35` and `MAX_TTS_CHARS = 240`. Eliminates fragmented speech.
  - `TTSQueue`: Dedicated `asyncio.Queue` worker serializing speech, with `cancel_current()` and `clear_queue()` to instantly cancel obsolete speech when new user tasks arrive.

### [`output/aggregator.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/output/aggregator.py)
- **Purpose**: Milestone aggregation, fluff stripping, and progress phrase deduplication (§15, §16, §46, §47).
- **Classes & Functions**:
  - `BANNED_PREFIXES`: Strips "I am currently...", "I am running...", "I'm starting...", "I am confirming...".
  - `OutputAggregator`: `sanitize_phrase()`, `is_duplicate()`, `aggregate_milestone()`.

### [`output/terminal.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/output/terminal.py)
- **Purpose**: Terminal renderer formatting clean milestone messages (`⚡ Kratos: <milestone>`) and completion notifications (`⚡ Kratos: ✓ Done`).

---

## 7. `src/kratos_agent/system/shell/`

Cross-platform shell abstraction, PowerShell compatibility, and CLIXML parsing (§26–§36).

### [`system/shell/__init__.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/system/shell/__init__.py)
- **Purpose**: Shell abstraction exports.

### [`system/shell/base.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/system/shell/base.py)
- **Purpose**: Shell data models.
- **Classes & Functions**:
  - `ShellInfo`: Dataclass (`name`, `version`, `platform`, `executable`, `supports_and_operator`, `supports_or_operator`).
  - `CommandResult`: Dataclass (`success`, `stdout`, `stderr`, `exit_code`, `error_type`).

### [`system/shell/detect.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/system/shell/detect.py)
- **Purpose**: Automatic environment shell detection.
- **Classes & Functions**:
  - `detect_shell()`: Determines whether Windows PowerShell 5.1, pwsh Core, CMD, or Bash is active, recording operator support.

### [`system/shell/renderer.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/system/shell/renderer.py)
- **Purpose**: Command translation and subprocess argv generation.
- **Classes & Functions**:
  - `render_powershell_script(cmd)`: Translates `&&` into `; if ($?) { ... }` and `||` into `; if (-not $?) { ... }` for PowerShell 5.1.
  - `render_command_argv(cmd, shell)`: Formats direct subprocess `argv` lists to bypass shell strings entirely.

### [`system/shell/output_parser.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/system/shell/output_parser.py)
- **Purpose**: PowerShell output parser and CLIXML cleaner.
- **Classes & Functions**:
  - `strip_clixml_progress(text)`: Removes `<Obj S="progress"...>` progress records.
  - `normalize_command_output(stdout, stderr, exit_code)`: Strips `#< CLIXML` blocks and decodes escape sequences (`_x000D__x000A_`).

---

## 8. `src/kratos_agent/live/`

Bidirectional multimodal streaming session with Gemini Live.

### [`live/__init__.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/live/__init__.py)
- **Purpose**: Live session exports.

### [`live/session.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/live/session.py)
- **Purpose**: Gemini Live connection, realtime media send/receive loops, asynchronous tool handling, and Extended Thinking interaction lifecycle (`interaction_status`).
- **Classes & Functions**:
  - `LiveSession`: Manages connection backoff, audio streaming, screen capture uploads, and tool calls.
  - `receive_loop()`: Dispatches incoming tool calls, feeds audio to speaker, buffers transcripts through `VoiceBuffer`, and triggers `VoiceEchoGuard`.
  - `LIVE_SYSTEM_PROMPT`: Instructions for Gemini Live forbidding follow-up questions ("Is there anything else...").

### [`live/microphone.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/live/microphone.py)
- **Purpose**: `sounddevice`-first microphone capture with PyAudio fallback, 16kHz PCM, VAD, device discovery, and Windows endpoint mute diagnostics.

### [`live/speaker.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/live/speaker.py)
- **Purpose**: 24kHz PCM speaker playback with sounddevice/PyAudio fallback and component health reporting.

### [`live/audio.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/live/audio.py)
- **Purpose**: Audio resampling, WAV encoding/decoding, and volume normalization.

### [`live/screen.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/live/screen.py)
- **Purpose**: Fast desktop screen grabber converting frames to JPEG for vision streaming.

### [`live/camera.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/live/camera.py)
- **Purpose**: OpenCV webcam capture stream.

### [`live/vision.py`](file:///c:/Users/thratos_Agent/src/kratos_agent/live/vision.py)
- **Purpose**: Vision mode coordinator (`camera`, `screen`, `both`, `off`).

### [`live/avatar.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/live/avatar.py)
- **Purpose**: Terminal animated ASCII/Unicode avatar reflecting listening, speaking, thinking, and executing states.

### [`live/router.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/live/router.py)
- **Purpose**: Voice intent router classifying whether speech is direct chat or an agent task.

### [`live/runtime.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/live/runtime.py) & [`live/bridge.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/live/bridge.py)
- **Purpose**: Inter-thread bridge between Gemini Live WebSocket loop and autonomous agent runner.
- **Classes & Functions**:
  - `KratosBridge.submit_task()`: Enforces `VoiceEchoGuard.should_suppress_mic()` and `TaskDeduplicator.is_duplicate()`.

### [`live/echo_guard.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/live/echo_guard.py)
- **Purpose**: Guards microphone input while TTS is active and enforces `VoiceSource.USER_MIC`.

### [`live/events.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/live/events.py)
- **Purpose**: Live session state models (`LiveState`, `LiveStatusHub`).

### [`live/config.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/live/config.py)
- **Purpose**: Configuration dataclass for Gemini Live parameters.

### [`live/narration.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/live/narration.py)
- **Purpose**: Translates runtime events into concise spoken feedback, omitting internal reasoning.

---

## 9. `src/kratos_agent/computer/`

Universal Computer Use and desktop automation subsystem.

### [`computer/__init__.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/__init__.py)
- **Purpose**: Computer subsystem exports.

### [`computer/manager.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/manager.py)
- **Purpose**: Central computer-use orchestrator with concurrency locking (`_execution_lock = threading.Lock()`) to prevent racing tasks (§50).
- **Classes & Functions**:
  - `ComputerManager`: Coordinates `observe()`, `execute_action()`, `run_task()`, and `verifier`.

### [`computer/observer.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/observer.py)
- **Purpose**: High-speed desktop environment observer.
- **Classes & Functions**:
  - `ComputerObserver.observe()`: Collects active window, window list, browser URL, clipboard, and interactive elements.

### [`computer/state_cache.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/state_cache.py)
- **Purpose**: Hash-based desktop state cache providing 0.009ms observation returns when the screen is unchanged.

### [`computer/state.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/state.py)
- **Purpose**: Data models for `ComputerState`, `ComputerAction`, `ActionResult`, and `ObservationDiff`.

### [`computer/executor.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/executor.py)
- **Purpose**: Action execution dispatcher following the priority ladder (Native API → A11y → Browser DOM → Semantic UI → Mouse/Keyboard → Vision).

### [`computer/planner.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/planner.py)
- **Purpose**: UI navigation planner for multi-window desktop workflows.

### [`computer/recovery.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/recovery.py)
- **Purpose**: Desktop failure recovery engine dismissing unexpected modals and refocusing windows.

### [`computer/verifier.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/verifier.py)
- **Purpose**: Programmatic action and task verifier (§12, §13, §17, §18, §19, §36).
- **Classes & Functions**:
  - `ComputerTaskResult`: Standard completion contract (`task_id`, `success`, `verified`, `evidence`, `error`).
  - `ActionVerifier`: Implements `verify_browser_url()`, `verify_browser_title()`, `verify_page_loaded()`, `verify_video_present()`, `verify_video_playing()`, `verify_foreground_window()`.

### [`computer/capabilities.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/capabilities.py)
- **Purpose**: Probes and caches system capabilities (display server, UIA, Playwright, Chrome).

### [`computer/permissions.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/permissions.py)
- **Purpose**: Checks OS-level screen capture and accessibility permissions.

---

### 9.1 `apps/`
- [`apps/launcher.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/apps/launcher.py): Launches applications by name or path.
- [`apps/windows.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/apps/windows.py): Window listing and Win32 `_activate_hwnd_win32()` foreground activation.
- [`apps/processes.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/apps/processes.py): Process listing and PID management.
- [`apps/focus.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/apps/focus.py): Focus management with verification and `restore_previous_window()`.
- [`apps/focus_policy.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/apps/focus_policy.py): Enum `FocusPolicy` (`KEEP_CURRENT`, `FOCUS_TARGET`, `RESTORE_PREVIOUS`).
- **`apps/adapters/`**:
  - [`adapters/__init__.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/apps/adapters/__init__.py): Adapter registry.
  - [`adapters/base.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/apps/adapters/base.py): Base application-specific adapter interface.

---

### 9.2 `browser/`
- [`browser/target.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/browser/target.py): Defines `BrowserTarget` and `BrowserTargetManager` maintaining active browser state across turns (§3).
- [`browser/manager.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/browser/manager.py): Single authority for browser lifecycle. Reuses existing Chrome windows and tabs before launching new processes (§1, §2, §4, §5).
- [`browser/playwright.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/browser/playwright.py): Playwright/CDP driver with `VideoPlaybackState`, time-advancing `verify_video_playing()`, and `search_and_play_youtube()` (§11–§13).
- [`browser/selector.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/browser/selector.py): `BrowserBackendSelector` prioritizing Playwright and active sessions over Selenium (§20, §21).
- [`browser/state_machine.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/browser/state_machine.py): `BrowserTaskState` and `BrowserActionRegistry` enforcing SHA-256 idempotency keys and retry limits (§14, §15, §16).

---

### 9.3 `filesystem/`
- [`filesystem/files.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/filesystem/files.py): Desktop file operations (open with default program, show in folder).
- [`filesystem/clipboard.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/filesystem/clipboard.py): Direct system clipboard read/write.

---

### 9.4 `gui/`
- [`gui/__init__.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/gui/__init__.py): GUI module exports.
- [`gui/resolver.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/gui/resolver.py): Resolves textual descriptions to UI element references or coordinates.
- [`gui/selectors.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/gui/selectors.py): CSS/XPath-like selector parser for accessibility trees.
- [`gui/inspector.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/gui/inspector.py): Fast accessibility tree crawler.
- [`gui/actions.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/gui/actions.py): GUI interaction actions.
- [`gui/models.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/gui/models.py): GUI element representations (`BoundingBox`, `WindowInfo`, `Rect`).
- [`gui/errors.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/gui/errors.py): GUI exception types.
- [`gui/manager.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/gui/manager.py): High-level GUI arbiter.
- **`gui/backends/`**:
  - [`backends/base.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/gui/backends/base.py): Base GUI backend interface.
  - [`backends/windows_uia.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/gui/backends/windows_uia.py): Windows UI Automation backend.
  - [`backends/linux_atspi.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/gui/backends/linux_atspi.py): Linux AT-SPI accessibility backend.
  - [`backends/playwright.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/gui/backends/playwright.py): Browser DOM accessibility backend.
  - [`backends/coordinate.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/gui/backends/coordinate.py): Coordinate fallback backend.
- **`gui/input/`**:
  - [`input/keyboard.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/gui/input/keyboard.py): Keyboard synthesis engine.
  - [`input/mouse.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/gui/input/mouse.py): Mouse synthesis engine.

---

### 9.5 `tools/`
- [`tools/__init__.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/tools/__init__.py): Tool exports.
- [`tools/computer_tools.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/tools/computer_tools.py): Computer control tool declarations.
- [`tools/browser_tools.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/tools/browser_tools.py): Browser tools (`computer_browser_navigate`, `computer_browser_read`, etc.).
- [`tools/gui_tools.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/tools/gui_tools.py): GUI inspection and action tools.
- [`tools/system_tools.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/tools/system_tools.py): Volume, display, and lock tools.

---

### 9.6 `vision/`
- [`vision/detector.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/vision/detector.py): Visual element detector for non-accessible canvas apps.
- [`vision/grounding.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/vision/grounding.py): Text label to bounding box grounding.
- [`vision/interpreter.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/vision/interpreter.py): Screen diff visual analyzer.

---

## 10. `src/kratos_agent/ccs/`

Low-level Cross-Platform Computer Subsystem drivers and hardware bindings.

### [`ccs/__init__.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/__init__.py)
- **Purpose**: CCS exports.

### [`ccs/base.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/base.py)
- **Purpose**: Base hardware driver interface defining platform-neutral contracts (`BasePlatformDriver`, `Point`, `Rect`).

### [`ccs/assertions.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/assertions.py)
- **Purpose**: Low-level post-action assertions.

### [`ccs/doctor.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/doctor.py)
- **Purpose**: Diagnostics tool inspecting OS version, display server, audio devices, and permissions.

### [`ccs/windows.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/windows.py) & [`ccs/linux.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/linux.py)
- **Purpose**: Win32/ctypes and Xlib platform drivers.

### [`ccs/discovery.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/discovery.py)
- **Purpose**: Discovery of running applications and display configurations.

### [`ccs/safety_ops.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/safety_ops.py)
- **Purpose**: Emergency failsafes (e.g. corner mouse move aborts).

### [`ccs/tasks.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/tasks.py)
- **Purpose**: Atomic automation tasks.

### [`ccs/plugin.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/plugin.py) & [`ccs/elevated_helper.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/elevated_helper.py)
- **Purpose**: Plugin definition and UAC elevated execution helpers.

---

### 10.1 `ccs/browser/`
- [`ccs/browser/__init__.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/browser/__init__.py): CDP exports.
- [`ccs/browser/cdp.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/browser/cdp.py): Chrome DevTools Protocol WebSocket client attaching to running Chrome instances.

### 10.2 `ccs/input/`
- [`ccs/input/windows.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/input/windows.py): Win32 `SendInput` synthesizing mouse clicks, drags, keyboard scan codes, and Unicode.
- [`ccs/input/hotkey.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/input/hotkey.py): Key combination simulator.
- [`ccs/input/interlock.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/input/interlock.py): Prevents simulated inputs when physical user input is detected.
- [`ccs/input/keys.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/input/keys.py): Virtual key and scan code mapping tables.

### 10.3 `ccs/perception/`
- [`ccs/perception/a11y_windows.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/perception/a11y_windows.py): Direct Win32 UI Automation COM wrapper.
- [`ccs/perception/blockers.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/perception/blockers.py): Automated detection of modal dialogs and alert popups.
- [`ccs/perception/screenshot.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/perception/screenshot.py): Sub-millisecond screenshot grabber.
- [`ccs/perception/screen_diff.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/perception/screen_diff.py): Screenshot differencing.
- [`ccs/perception/ocr.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/perception/ocr.py): Windows Media OCR / Tesseract wrapper.
- [`ccs/perception/grounding.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/perception/grounding.py): DPI scaling and coordinate converter.
- [`ccs/perception/cache.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/perception/cache.py): Perception cache.

### 10.4 `ccs/system/`
- [`ccs/system/elevation.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/system/elevation.py): Manages administrator elevation requests.

---

## 11. `src/kratos_agent/memory/`

Layered Cognitive Memory Architecture V2.

### [`memory/__init__.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/memory/__init__.py)
- **Purpose**: Memory module exports.

### [`memory/models.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/memory/models.py)
- **Purpose**: Data models for the 6 cognitive layers (`WORKING`, `EPISODIC`, `SEMANTIC`, `PROCEDURAL`, `APPLICATION`, `ERROR`) and 7 scopes (`TASK`, `SESSION`, `PROJECT`, `APPLICATION`, `USER`, `GLOBAL`, `WORKFLOW`).

### [`memory/manager.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/memory/manager.py)
- **Purpose**: `MemoryManager` providing 0.08ms hot-cache lookups, multi-factor ranking, and asynchronous background consolidation.

### [`memory/ranking.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/memory/ranking.py)
- **Purpose**: Multi-factor hybrid ranking algorithm combining similarity (30%), task relevance (25%), importance (15%), confidence (15%), recency (5%), frequency (5%), and context match (5%).

### [`memory/decay.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/memory/decay.py)
- **Purpose**: Layer-specific decay and verified execution reinforcement.

### [`memory/consolidation.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/memory/consolidation.py)
- **Purpose**: Background deduplication and semantic fact clustering.

### [`memory/store.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/memory/store.py)
- **Purpose**: SQLite and in-memory vector/metadata storage engine.

### Specialized Memory Layers
- [`memory/working.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/memory/working.py): Active task state and recent step variables.
- [`memory/procedural.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/memory/procedural.py): Multi-step workflow recipes and keyboard shortcuts.
- [`memory/application.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/memory/application.py): App-specific settings, flags, and facts.
- [`memory/errors.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/memory/errors.py): Failure signatures and verified recovery strategies.

---

## 12. `src/kratos_agent/utils/` & `tools/`

Primary tool implementations, helpers, and setup scripts.

### [`utils/__init__.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/utils/__init__.py)
- **Purpose**: Tool utility exports.

### [`utils/tools.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/utils/tools.py)
- **Purpose**: Primary tool handlers (`read_file`, `write_file`, `edit_file`, `list_directory`, `grep_search`, `run_terminal_command`, `web_search`) with shell rendering and output normalization.

### [`utils/computer_tools.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/utils/computer_tools.py)
- **Purpose**: 850+ lines of comprehensive desktop automation tools (`screenshot_capture`, `screen_read_text`, `ui_tree_dump`, `ui_find`, `mouse_click`, `keyboard_type`, etc.).

### [`utils/shell_quote.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/utils/shell_quote.py)
- **Purpose**: Argument escaping for Windows CMD, PowerShell, and Unix shells.

### [`utils/tool_creator.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/utils/tool_creator.py)
- **Purpose**: Dynamically creates and registers new Python tools at runtime.

### [`utils/step_tracker.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/utils/step_tracker.py)
- **Purpose**: Enforces turn limits and step budgets.

### [`utils/sync_tools.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/utils/sync_tools.py)
- **Purpose**: Synchronizes tool definitions with `tools_list.json`.

### [`utils/tools_list.json`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/utils/tools_list.json)
- **Purpose**: Static JSON schema catalog of all built-in tools.

### [`tools/d1_setup.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/tools/d1_setup.py)
- **Purpose**: Setup script initializing Cloudflare D1 tables.

---

## 13. `src/kratos_agent/tui/` & `web/`

Terminal User Interface and Browser-Based Web UI.

### `tui/` (Terminal UI)
- [`tui/__init__.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/tui/__init__.py): TUI exports.
- [`tui/live_renderer.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/tui/live_renderer.py): Rich live display split into main interaction area, thought box, and status bar.
- [`tui/debug_panel.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/tui/debug_panel.py): Real-time debug panel showing latency, tool outputs, and memory hits.
- [`tui/status_bar.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/tui/status_bar.py): Bottom status bar displaying model, mode, voice/vision state, and tokens.
- [`tui/completion_view.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/tui/completion_view.py): Formats final response with evidence summaries.
- [`tui/stream_printer.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/tui/stream_printer.py): Smooth streaming token printer with syntax highlighting.
- [`tui/events.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/tui/events.py): UI event definitions.

### `web/` (Web Application & Server)
- [`web/__init__.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/web/__init__.py): Web module exports.
- [`web/server.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/web/server.py): FastAPI & WebSocket server exposing Kratos as a browser web application (`/`, `/ws`, `/api/task`).
- [`web/index.html`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/web/index.html): Modern web UI with live chat, voice controls, and vision viewports.
- [`web/highlighter.js`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/web/highlighter.js) & [`web/highlighter.json`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/web/highlighter.json): Client-side syntax highlighter.
- [`web/assets/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/web/assets): Compiled CSS and JavaScript application bundles.
- [`web/fonts/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/web/fonts): Custom pixel/UI fonts (`Pixl-1awM.otf`, `Pixl-D6OR.ttf`).
- Static assets: `favicon.svg`, `icons.svg`, `kratos_badge.png`, `kratos_banner.jpg`.

---

## 14. `docs/`

Architectural guides and design documents.

- [`docs/CODEBASE_MAP.md`](file:///c:/Users/thiru/Documents/Kratos_Agent/docs/CODEBASE_MAP.md): High-level codebase overview.
- [`docs/architecture.md`](file:///c:/Users/thiru/Documents/Kratos_Agent/docs/architecture.md): Runtime architecture and request contract specification.
- [`docs/COMPUTER_USE.md`](file:///c:/Users/thiru/Documents/Kratos_Agent/docs/COMPUTER_USE.md): Autonomous desktop and computer-use guide.
- [`docs/GUI_AUTOMATION.md`](file:///c:/Users/thiru/Documents/Kratos_Agent/docs/GUI_AUTOMATION.md): GUI accessibility tree navigation and element resolution guide.
- [`docs/cloudflare_d1_setup.md`](file:///c:/Users/thiru/Documents/Kratos_Agent/docs/cloudflare_d1_setup.md): Cloudflare D1 distributed memory setup.
- [`docs/SECURITY.md`](file:///c:/Users/thiru/Documents/Kratos_Agent/docs/SECURITY.md): Sandboxing, approval policies, and execution safety.

---

## 15. Root Workspace Files & Build Scripts

Core scripts, deployment configurations, and specifications residing at the root of `Kratos_Agent/`.

### [`live.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/live.py)
- **Purpose**: Standalone interactive Gemini Live multimodal streaming client connecting to Google GenAI Live API over WebSockets.
- **Classes & Functions**:
  - `AudioLoop`: Captures microphone audio at 16kHz PCM and streams it to the Gemini Live session.
  - `AudioPlayback`: Receives 24kHz PCM audio chunks and outputs them to the speaker via PyAudio.
  - `ScreenCapture`: Captures screen frames using `mss`, encodes them as JPEG, and streams them for visual grounding.
  - `CameraCapture`: Captures webcam video via OpenCV and streams frames.
  - `main()`: CLI entry point supporting `--mode camera`, `--mode screen`, or `--mode none`.
- **Use Case**: Direct testing and debugging of the real-time Gemini Live audio/video stream independent of the full agent orchestrator.
- **Connections**: Precursor and testing prototype for `src/kratos_agent/live/`.

### [`kratos_entry.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/kratos_entry.py)
- **Purpose**: Clean frozen executable entry point for PyInstaller Windows builds.
- **Classes & Functions**:
  - Sets up `sys.path` to include `src/` and project root.
  - Configures Windows terminal standard streams (`stdout`, `stderr`, `stdin`) to UTF-8 encoding.
  - Dispatches execution to `kratos_agent.cli:main()`.
- **Use Case**: Target entry script for `build_exe.py` and PyInstaller.

### [`worker.js`](file:///c:/Users/thiru/Documents/Kratos_Agent/worker.js)
- **Purpose**: Serverless Cloudflare Worker edge backend (1,685 lines) executing the full autonomous Kratos pipeline on Cloudflare's edge network.
- **Classes & Functions**:
  - `handleApi(request, env, url)`: Central REST and SSE router handling `/api/chat`, `/api/task`, `/api/sessions`, `/api/files`, `/api/sql`, and `/api/traces`.
  - `executeAgentLoop(query, env, ...)`: Serverless multi-turn agent loop driving tool execution, D1 SQL queries, virtual workspace file manipulations, and SSE step streaming.
  - `getSchemaSql()`: Returns the Cloudflare D1 relational schema for sessions, events, memory, and virtual files.
  - `TOOLS_LIST`: Catalog of 14 core tools implemented directly in the edge JavaScript worker.
- **Use Case**: Powers the serverless web dashboard and remote agent execution on Cloudflare Workers/Pages.
- **Connections**: Interfaced by `functions/api/[[path]].js` and `frontend/src/App.jsx`.

### [`build_exe.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/build_exe.py), [`build_exe.ps1`](file:///c:/Users/thiru/Documents/Kratos_Agent/build_exe.ps1) & [`build.bat`](file:///c:/Users/thiru/Documents/Kratos_Agent/build.bat)
- **Purpose**: Automated build scripts packaging Kratos Agent into a standalone Windows executable (`dist/kratos.exe`).
- **Classes & Functions**:
  - `prepare_icon()`: Generates `kratos.ico` from `kratos_banner.png` across multiple resolutions (256x256 down to 16x16).
  - `run_build()`: Executes PyInstaller with `--noconfirm`, `--clean`, and `kratos_agent.spec`.
- **Use Case**: Creates single-binary distributables for Windows without requiring Python or pip.

### [`kratos_agent.spec`](file:///c:/Users/thiru/Documents/Kratos_Agent/kratos_agent.spec)
- **Purpose**: PyInstaller configuration specification defining binary packaging details, data files, icon bundles, and hidden imports.

### [`pyproject.toml`](file:///c:/Users/thiru/Documents/Kratos_Agent/pyproject.toml)
- **Purpose**: Modern Python project metadata (PEP 518/621) and build configuration using `hatchling`. Defines the `kratos` command-line executable (`kratos = "kratos_agent.cli:main"`).

### [`requirements.txt`](file:///c:/Users/thiru/Documents/Kratos_Agent/requirements.txt)
- **Purpose**: Comprehensive list of dependencies for local pip and virtual environments (FastAPI, uvicorn, textual, rich, mss, opencv-python, pyaudio, google-genai, pillow, playwright, etc.).

### [`package.json`](file:///c:/Users/thiru/Documents/Kratos_Agent/package.json)
- **Purpose**: Workspace npm package definition managing Wrangler and build tools for Cloudflare deployment.

### [`wrangler.json`](file:///c:/Users/thiru/Documents/Kratos_Agent/wrangler.json)
- **Purpose**: Cloudflare Pages / Workers deployment configuration binding D1 database (`kratos-db`), setting compatibility dates, and defining routing rules.

### [`KRATOS.md`](file:///c:/Users/thiru/Documents/Kratos_Agent/KRATOS.md)
- **Purpose**: Workspace-level project memory file containing established project facts, coding rules, and conventions loaded by `core/project_memory.py`.

### [`README.md`](file:///c:/Users/thiru/Documents/Kratos_Agent/README.md)
- **Purpose**: Main repository documentation presenting feature highlights, architecture overviews, installation guides, CLI usage examples, and web UI guides.

### [`JARVIS-SOVEREIGN-SPEC.md`](file:///c:/Users/thiru/Documents/Kratos_Agent/JARVIS-SOVEREIGN-SPEC.md)
- **Purpose**: Master architectural and behavioral specification (240KB) defining the autonomous sovereign agent philosophy, execution contracts, tool rules, and performance budgets.

---

## 16. `documentation/`

Structured reference manuals providing in-depth guides for developers, systems engineers, and API consumers.

- [`documentation/README.md`](file:///c:/Users/thiru/Documents/Kratos_Agent/documentation/README.md): Index and reading guide for the technical documentation library.
- [`documentation/architecture.md`](file:///c:/Users/thiru/Documents/Kratos_Agent/documentation/architecture.md): Deep-dive into the Kratos Agent architectural layers, multi-turn loop, and subsystem communication contracts.
- [`documentation/brain-reference.md`](file:///c:/Users/thiru/Documents/Kratos_Agent/documentation/brain-reference.md): Technical specification for the Brain gateway, OmniRoute protocol, and model adapter contracts.
- [`documentation/file-catalog.md`](file:///c:/Users/thiru/Documents/Kratos_Agent/documentation/file-catalog.md): Component-level catalog mapping core files to system responsibilities.
- [`documentation/frontend-reference.md`](file:///c:/Users/thiru/Documents/Kratos_Agent/documentation/frontend-reference.md): Architectural guide for the React + Vite frontend, explaining SSE streaming, tab state, and components.
- [`documentation/python-reference.md`](file:///c:/Users/thiru/Documents/Kratos_Agent/documentation/python-reference.md): Python coding guidelines, typing standards, asynchronous patterns, and error-handling idioms.
- [`documentation/testing-and-build.md`](file:///c:/Users/thiru/Documents/Kratos_Agent/documentation/testing-and-build.md): Guide to running pytest test suites, benchmark harnesses, and packaging Windows binaries.
- [`documentation/tools-and-data.md`](file:///c:/Users/thiru/Documents/Kratos_Agent/documentation/tools-and-data.md): Detailed specifications for built-in tools, argument schemas, execution timeouts, and D1 database tables.
- [`documentation/web-api.md`](file:///c:/Users/thiru/Documents/Kratos_Agent/documentation/web-api.md): REST and WebSocket API reference for `/api/chat`, `/api/task`, `/api/sessions`, and `/ws`.

---

## 17. `frontend/`

Vite + React modern cybernetic dashboard deployed to Cloudflare Pages.

### Configuration & Entry
- [`frontend/index.html`](file:///c:/Users/thiru/Documents/Kratos_Agent/frontend/index.html): HTML5 entry point mounting `#root` and loading Google Fonts (Outfit, Inter).
- [`frontend/vite.config.js`](file:///c:/Users/thiru/Documents/Kratos_Agent/frontend/vite.config.js): Vite build configuration with React plugin and development server proxy routing.
- [`frontend/package.json`](file:///c:/Users/thiru/Documents/Kratos_Agent/frontend/package.json): Frontend npm package manifest (`react`, `lucide-react`, `tailwindcss`, `vite`).
- [`frontend/src/main.jsx`](file:///c:/Users/thiru/Documents/Kratos_Agent/frontend/src/main.jsx): React application bootstrapping.
- [`frontend/src/App.jsx`](file:///c:/Users/thiru/Documents/Kratos_Agent/frontend/src/App.jsx): Main dashboard state orchestrator managing tabs, live SSE connections, chat history, and telemetry.
- [`frontend/src/App.css`](file:///c:/Users/thiru/Documents/Kratos_Agent/frontend/src/App.css) & [`frontend/src/index.css`](file:///c:/Users/thiru/Documents/Kratos_Agent/frontend/src/index.css): Cyberpunk/modern dark mode CSS styles, glassmorphism tokens, and layout styling.

### UI Components (`frontend/src/components/`)
- [`AgentArena.jsx`](file:///c:/Users/thiru/Documents/Kratos_Agent/frontend/src/components/AgentArena.jsx): Central interactive arena displaying conversation turns, streaming tokens, step cards, and tool badges.
- [`AgentHud.jsx`](file:///c:/Users/thiru/Documents/Kratos_Agent/frontend/src/components/AgentHud.jsx): Telemetry Heads-Up Display showing CPU/memory metrics, active model, token headroom, and subagent state.
- [`MarkdownRenderer.jsx`](file:///c:/Users/thiru/Documents/Kratos_Agent/frontend/src/components/MarkdownRenderer.jsx): GitHub Flavored Markdown renderer with syntax-highlighted code blocks and copy buttons.
- [`Modals.jsx`](file:///c:/Users/thiru/Documents/Kratos_Agent/frontend/src/components/Modals.jsx): Dialog modals for tool approval confirmation, API key configuration, and settings.
- [`Navbar.jsx`](file:///c:/Users/thiru/Documents/Kratos_Agent/frontend/src/components/Navbar.jsx): Top navigation bar with active session switcher, live status badge, and view toggles.
- [`RecruiterStrip.jsx`](file:///c:/Users/thiru/Documents/Kratos_Agent/frontend/src/components/RecruiterStrip.jsx): Professional showcase banner highlighting autonomous architecture features.
- [`SessionsExplorer.jsx`](file:///c:/Users/thiru/Documents/Kratos_Agent/frontend/src/components/SessionsExplorer.jsx): Historical session browser querying Cloudflare D1 records.
- [`SqlPlayground.jsx`](file:///c:/Users/thiru/Documents/Kratos_Agent/frontend/src/components/SqlPlayground.jsx): In-browser SQL editor allowing live queries against the Cloudflare D1 database.
- [`TraceReplay.jsx`](file:///c:/Users/thiru/Documents/Kratos_Agent/frontend/src/components/TraceReplay.jsx): Interactive visual trace timeline for step-by-step replay and debugging of agent executions.

---

## 18. `functions/`

Cloudflare Pages Functions middleware connecting edge HTTP requests to the worker runtime.

### [`functions/api/[[path]].js`](file:///c:/Users/thiru/Documents/Kratos_Agent/functions/api/[[path]].js)
- **Purpose**: Catch-all Pages Functions route handler for `/api/*`.
- **Classes & Functions**:
  - `onRequest(context)`: Intercepts all incoming API requests, resolves CORS pre-flight (`OPTIONS`), auto-initializes the Cloudflare D1 database schema on first run, and delegates execution to `worker.js:handleApi()`.
- **Use Case**: Enables full serverless API execution directly on Cloudflare Pages without a separate server.

---

## 19. `tests/`

Exhaustive test suite, regression guards, and latency benchmarks.

### Root Test Modules (`tests/`)
- [`test_agent_execution_ux.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_agent_execution_ux.py): Verifies user-visible milestone formatting and absence of raw internal noise.
- [`test_agent_orchestration_loop.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_agent_orchestration_loop.py): Validates multi-turn agent loop execution and tool dispatching.
- [`test_assertions.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_assertions.py): Verifies low-level post-action assertion contracts.
- [`test_avatar_and_decision_matrix.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_avatar_and_decision_matrix.py): Tests terminal avatar animation states and live decision matrices.
- [`test_blockers.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_blockers.py): Verifies automated detection of modal dialogs and popup blockers.
- [`test_brain_config.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_brain_config.py) & [`test_brain_transport.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_brain_transport.py): Tests Brain gateway configuration parsing and HTTP/WebSocket transport.
- [`test_ccs_doctor.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_ccs_doctor.py): Tests system diagnostics and environment capability inspection.
- [`test_ccs_no_stubs.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_ccs_no_stubs.py): Enforces that all Cross-Platform Computer Subsystem methods are fully implemented without stub `pass` statements.
- [`test_cognitive_memory.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_cognitive_memory.py): Tests the 6 cognitive memory layers, multi-factor ranking, and decay rules.
- [`test_command_lint.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_command_lint.py): Tests static security analysis of shell commands.
- [`test_completion_gate.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_completion_gate.py): Enforces that tasks cannot declare completion without verifiable evidence.
- [`test_d1_client.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_d1_client.py) & [`test_d1_storage.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_d1_storage.py): Tests Cloudflare D1 client queries, schema initialization, and offline fallback.
- [`test_deepseek_harness.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_deepseek_harness.py): Tests DeepSeek reasoning tag extraction and harness integration.
- [`test_dispute.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_dispute.py): Tests hallucination detection by comparing agent claims against actual tool output.
- [`test_dynamic_agent_planning.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_dynamic_agent_planning.py): Tests dynamic task replanning when intermediate steps fail.
- [`test_event_bus.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_event_bus.py): Tests asynchronous event dispatching, subscriber callbacks, and filtering.
- [`test_evidence_contract.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_evidence_contract.py): Tests strict validation of evidence contracts.
- [`test_false_completion.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_false_completion.py) & [`test_false_completion_gui.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_false_completion_gui.py): Regression tests preventing premature completion claims in CLI and GUI automation.
- [`test_headroom_integration.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_headroom_integration.py): Tests token headroom calculations and context pruning.
- [`test_input_speed.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_input_speed.py): Verifies sub-millisecond input synthesis speed.
- [`test_latency_and_verification_timing.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_latency_and_verification_timing.py): Verifies latency tracking checkpoints and timing budgets.
- [`test_live_components.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_live_components.py) & [`test_live_renderer_wiring.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_live_renderer_wiring.py): Tests Gemini Live audio/video streaming and TUI live renderer wiring.
- [`test_narrator_honesty.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_narrator_honesty.py): Ensures spoken voice narration never claims an action succeeded before verification finishes.
- [`test_no_fixed_sleeps.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_no_fixed_sleeps.py): Static code audit ensuring no arbitrary `time.sleep()` calls exist in core pipelines.
- [`test_no_shell_true.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_no_shell_true.py): Static audit ensuring subprocess invocations do not use dangerous `shell=True`.
- [`test_parallel_execution.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_parallel_execution.py) & [`test_parallel_output_dedup.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_parallel_output_dedup.py): Tests parallel tool wave execution and output stream deduplication.
- [`test_perception_cache.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_perception_cache.py) & [`test_perception_checkpoints.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_perception_checkpoints.py): Tests screen perception caching and verification checkpoints.
- [`test_planner.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_planner.py): Tests intent classification and multi-step plan decomposition.
- [`test_runtime.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_runtime.py): Tests programmatic agent runtime execution.
- [`test_shell_quote.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_shell_quote.py): Tests cross-platform shell argument escaping.
- [`test_status_truthfulness.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_status_truthfulness.py): Validates truthful status reporting across all agent phases.
- [`test_stream_response.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_stream_response.py): Tests streaming token yielding and cancellation.
- [`test_task_manager.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_task_manager.py): Tests task state transitions, priority queues, and history tracking.
- [`test_terminal_latch.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_terminal_latch.py): Tests terminal UI layout stability.
- [`test_tool_calling_loop.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_tool_calling_loop.py) & [`test_tool_registry_complete.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_tool_registry_complete.py): Tests tool execution loops and verifies all tools have valid schemas.
- [`test_unicode_typing.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_unicode_typing.py): Tests Windows `SendInput` Unicode keyboard injection for non-ASCII characters.
- [`test_url_encoding.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_url_encoding.py): Tests URL query parameter encoding and parsing.
- [`test_web_live_chat.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/test_web_live_chat.py): Tests WebSocket live chat protocol and message serialization.

### Specialized Test Subdirectories (`tests/`)
- **`tests/benchmarks/`**:
  - [`benchmarks/computer_use/test_benchmark_runner.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/benchmarks/computer_use/test_benchmark_runner.py): Benchmarks computer-use action latency, state capture, and verification timings.
  - [`benchmarks/performance/test_perf_benchmark.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/benchmarks/performance/test_perf_benchmark.py): Validates performance budgets (<0.5ms routing, <0.1ms prompt construction, <0.1ms memory recall).
- **`tests/browser/`**:
  - [`browser/test_browser_control.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/browser/test_browser_control.py): Tests Playwright browser actions, page navigation, and DOM element interactions.
- **`tests/computer/`**:
  - [`computer/test_browser_direct_path.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/computer/test_browser_direct_path.py): Tests fast-path routing directly to browser tools without planning overhead.
  - [`computer/test_browser_target.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/computer/test_browser_target.py): Tests persistent browser target tracking and multi-tab management.
  - [`computer/test_computer_state.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/computer/test_computer_state.py): Tests desktop state models, screen hashing, and diff calculation.
  - [`computer/test_focus_policy.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/computer/test_focus_policy.py): Tests window focus policies (`KEEP_CURRENT`, `FOCUS_TARGET`, `RESTORE_PREVIOUS`).
  - [`computer/test_observer_diff.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/computer/test_observer_diff.py): Tests accessibility tree diffing and visual change detection.
  - [`computer/test_recovery_engine.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/computer/test_recovery_engine.py): Tests automatic modal dismissal, focus recovery, and retry logic.
  - [`computer/test_video_verification.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/computer/test_video_verification.py): Tests time-advancing video playback verification.
- **`tests/core/`**:
  - [`core/test_task_deduplicator.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/core/test_task_deduplicator.py): Tests duplicate task suppression within the 3-second window.
- **`tests/gui/`**:
  - [`gui/test_semantic_resolver.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/gui/test_semantic_resolver.py): Tests semantic element resolution from textual descriptions to accessibility elements.
- **`tests/live/`**:
  - [`live/test_echo_guard.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/live/test_echo_guard.py): Tests microphone suppression during audio playback to prevent acoustic echo loops.
- **`tests/memory/`**:
  - [`memory/test_layered_memory.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/memory/test_layered_memory.py): Tests layered memory indexing, hybrid ranking, and decay mechanics.
- **`tests/output/`**:
  - [`output/test_user_output.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/output/test_user_output.py): Tests output filtering across NORMAL, DEBUG, and SILENT modes.
  - [`output/test_voice_buffer.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/output/test_voice_buffer.py): Tests voice sentence buffering and chunk size boundaries.
- **`tests/performance/`**:
  - [`performance/test_request_router.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/performance/test_request_router.py): Tests request categorization accuracy and fast-path determination.
  - [`performance/test_state_cache.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/performance/test_state_cache.py): Tests desktop state hash caching for sub-millisecond repeated observations.
  - [`performance/test_tool_filtering.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/performance/test_tool_filtering.py): Tests category-based tool schema filtering for token reduction.
- **`tests/system/`**:
  - [`system/test_shell_abstraction.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/tests/system/test_shell_abstraction.py): Tests PowerShell script rendering, CLIXML stripping, and operator translation.



### Gemini 3.8 Extended Thinking integration requirements
`behavior="NON_BLOCKING"` is required on Live function declarations. `interaction_status` is tracked in the receive loop because `turnComplete` is not sufficient to identify the end of an Extended Thinking interaction. Tool responses do not use function scheduling directives because scheduling configurations are not supported by the Extended Thinking Live model.
