# Python Runtime Reference

## Composition and CLI

### `src/kratos_agent/main.py`

`KratosRuntime(model_name=DEFAULT_MODEL, workspace=None)` composes instructions, context, legacy tools, MCP, brain/model adapters, memory, event storage, the explicit `AgentLoop`, and subagents.

Methods:

- `_register_instruction_modules()`: registers core safety, developer workflow, workspace/project memory, skills, and engineering guideline instruction layers.
- `_restore_history() -> list[ChatMessage]`: converts the active session's stored turns into alternating user/assistant messages.
- `_open_event_store() -> EventStore`: binds trace storage to the active session directory and optional database.
- `activate_session()`: reloads history and event storage after a session switch.
- `_emit(event)`: persists events and captures the assembled request/current tool calls.
- `_run_isolated(role, history) -> str`: creates a role-scoped child instruction engine and runs an isolated child loop.
- `cancel()` / `clear_cancel()`: set or clear the turn cancellation event.
- `reload_tools()`: rebuilds the legacy registry and updates the active loop.
- `set_model(model_name)`: rebuilds Brain objects and updates the active session model.
- `_allow_tool(spec, arguments) -> tuple[bool, str]`: enforces permission type, workspace containment, approval mode, and shell safety.
- `invoke(messages) -> str`: assembles a turn, invokes the loop, stores the resulting conversation, and returns the reply.

Module globals include `runtime`, the singleton runtime, and the exported system prompt.

### `src/kratos_agent/cli.py`

The CLI uses prompt-toolkit for input/completion and Rich for output. Important helpers/handlers include:

- `normalize_command(cmd_str)`: collapses duplicate leading slashes.
- `get_kratos_banner()`: selects ASCII or optional image output based on `KRATOS_IMAGE_BANNER`.
- `KratosCompleter.get_completions(document, complete_event)`: completes slash commands, model names, skill names, and `@file` paths.
- command handlers for health/gateway/session/model/memory/compact/review/simplify/security/tools/skills/reload/background tasks/context/debug/mode/web/D1.
- `run_cli()`: owns the interactive prompt loop and dispatches slash commands or user prompts.
- `main()`: parses CLI flags for web, CLI, and one-shot operation.

## Core execution modules

### `core/agent_loop.py`

`AgentLoop(context, instructions, tools, model, emit, workspace, cancellation_flag=None)` owns execution state.

- `format_tool_action_label(name, args)` and private substep formatters produce user-facing action text.
- `emit(event)`: sends an event to the runtime callback and global bus.
- `cancel()` / `clear_cancel()`: manage cancellation.
- `_track_tool_side_effects(name, args, is_error, turn_id)`: records changed/inspected files and commands and emits matching events.
- `run(history, allow_tool, max_steps=24, resume_plan=None) -> (str, list[ChatMessage])`: classifies intent, creates/resumes plans, repeatedly assembles context and calls the model, executes tool calls, updates tasks, verifies changes, and returns the reply/history.

### `core/planner.py` and `core/task_manager.py`

`classify_intent(user_query, history=[]) -> IntentKind` chooses chat/question/coding/build/test/deployment/refactoring/security/review/simplify categories. `formulate_agent_plan(user_query, model, workspace, instructions=None)` asks the model for structured tasks and returns an `ExecutionPlan`.

`TaskState` and `AgentState` are string enums. `TaskItem` stores `id`, `title`, `description`, `state`, `depends_on`, `started_at`, `completed_at`, `error`, and `notes`; methods include `start`, `complete`, `fail`, `pause`, `to_dict`, and `from_dict`. `ExecutionPlan` stores tasks and state; methods include `get_active_task`, `get_pending_tasks`, `start_task`, `update_task`, `complete_task`, `pause_running_tasks`, `is_complete`, `to_dict`, and `from_dict`.

### Other core services

- `approval_mode.py`: `is_dangerous_command(command)`, `ApprovalMode`, and `ApprovalGate.check_shell`, `check_write`, `set_mode`, `mode_badge`; singleton `approval_gate` persists `.kratos/settings.json`.
- `context_pipeline.py`: `ContextBudget` limits system/history/tool context; `ContextBuilder.assemble(instructions, history, tools, runtime_metadata)` returns the request plus compaction metadata; `build_context` is the compatibility helper.
- `instruction_engine.py`: `InstructionModule` describes a named layer/provider/priority; `InstructionEngine.register`, `unregister`, `build`, and `as_system_text` combine ordered instruction content.
- `provider_runtime.py`: `BrainAdapter` translates runtime requests to the Brain client and filters tool-call streams; `complete`/`stream` return text and normalized calls while preserving model/tool metadata.
- `runtime_contracts.py`: `ChatMessage`, `ToolSpec`, `ToolCall`, `ToolResult`, `RuntimeEvent`, `EventKind`, and `ToolPermission` define cross-layer data contracts.
- `verification_manager.py`: `VerificationResult` stores pass/failure, summary, details, build/test/browser flags, and file count. `VerificationManager.verify_workspace(changed_files, verification_type="auto", require_files=True, browser_performed=False, turn_id="")` checks existence, non-empty files, Python AST, JSON, and basic HTML/source structure.
- `workspace_tracker.py`: records created, modified, inspected files and commands for a turn; exposes reset, record, and summary methods.
- `event_bus.py`: thread-safe subscribe/unsubscribe/publish/discard operations for `RuntimeEvent` listeners.
- `event_store.py`: appends/reads JSONL event traces and mirrors events to the optional D1 store.
- `latency_tracker.py`: `RequestMetrics` tracks request start, first token, completion, token counts and durations; `LatencyTracker` starts/marks/finishes and formats diagnostics.
- `memory.py`: `AgenticSession` holds turn history, plans, files, verification, notes, and command records. `MemoryManager` creates/loads/saves/deletes sessions, records turns/commands, compacts history, and exposes the active session. Global `memory` is the manager.
- `compactor.py`: summarizes or compacts old messages when context budgets are exceeded.
- `background_runner.py`: starts, tracks, reports, and cancels background prompts using task IDs.
- `d1_client.py`: `D1Client` executes local SQLite or Cloudflare REST queries and returns rows; migration/schema helpers initialize tables.
- `d1_schema.sql`: canonical relational schema for sessions, turns, events, commands, and workspace files.
- `git_tools.py`: status/diff/commit/push/PR helpers used by the tools layer.
- `hooks.py`: `HookRegistry` registers callbacks and fires pre/post tool hooks.
- `mcp_runtime.py`: `McpManager` loads `.kratos/mcp.json`, discovers MCP servers/tools, and adapts them into registry specs.
- `project_memory.py`: reads/writes `KRATOS.md` project context.
- `prompt_library.py`: searches bundled Claude-style prompt resources and returns engineering guidelines.
- `reloader.py`: reloads Python modules and refreshes runtime tool/skill state.
- `skills.py`: `SkillManager` lists, installs, reads, removes, and formats local skill modules.
- `subagents.py`: `SubagentManager` creates role-based child runs through the runtime isolation callback.
- `tool_runtime.py`: `ToolRegistry.register`, `schemas`, `specs`, `execute`, and `_validate` form the validated execution boundary; `legacy_tool_registry(workspace)` imports handlers from the curated tool module and derives schemas with `_signature_schema`.
