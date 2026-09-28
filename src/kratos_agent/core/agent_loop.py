"""Autonomous agent loop for Kratos with intent classification, structured planning,
live task tree progression, workspace tracking, verification, and resilient interrupt/resume.
"""
from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

import inspect
import json
import os
import re
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from kratos_agent.brain.config import (
    get_max_parallel_workers,
    is_parallel_execution_enabled,
)
from kratos_agent.performance.profiler import reset_active_profiler
from kratos_agent.performance.router import RequestCategory, get_request_router

from .context_pipeline import ContextBuilder
from .event_bus import event_bus
from .planner import IntentKind, classify_intent, formulate_agent_plan
from .runtime_contracts import (
    AgentRunState,
    ChatMessage,
    EventKind,
    RuntimeEvent,
    TerminalLatch,
    ToolCall,
    ToolResult,
)
from .task_manager import AgentState, ExecutionPlan, TaskItem, TaskState
from .verification_manager import VerificationManager, VerificationResult
from .workspace_tracker import WorkspaceTracker
from kratos_agent.output.speech_directives import DirectiveStreamFilter, extract_speech_directives

# Tools that are read-only and have zero side effects on filesystem or workspace state.
# These can always execute concurrently with other read-only tools.
READ_ONLY_TOOLS = {
    "read_file",
    "list_directory",
    "grep_search",
    "fetch_url",
    "google_search",
    "web_search_duckduckgo",
    "read_memory",
    "git_status",
    "git_diff",
    "git_log",
    "read_symbol",
    "search_symbol",
    "view_outline",
    "read_skill",
    "list_skills",
    "spawn_subagent",
    "get_web_trace",
    # Desktop/browser read-only perception can run together; they do not mutate workspace state.
    "active_window_info",
    "app_list_running",
    "computer_file_list",
    "computer_file_read",
    "computer_process_list",
    "computer_browser_read",
    "computer_window_list",
    "computer_observe",
    "computer_inspect",
    "computer_find",
    "browser_read",
    "browser_state",
    "browser_snapshot_dom",
    "detect_blockers",
    "disk_info",
    "display_info",
    "ui_find",
    "ui_find_all",
    "ui_read_element",
}

ARTIFACT_INSPECTION_TOOLS = {
    "read_file", "list_directory", "grep_search", "search_symbol", "read_symbol", "view_outline",
}

# Tools that must run in isolation (sequential barriers)
BARRIER_TOOLS = {
    "run_terminal_command",
    "spawn_parallel_subagents",
    "todo_write",
    "exit_plan_mode",
    "save_memory",
    "clear_memory",
}


def partition_tool_waves(calls: list[ToolCall]) -> list[list[ToolCall]]:
    """Partitions a sequence of tool calls into waves of mutually independent batches.

    Guarantees:
    - Pure read-only calls are grouped into concurrent batches.
    - Write/edit calls targeting distinct file paths can run in parallel.
    - Repeated file targets are split across separate waves.
    - Barrier tools (shell commands, plan state transitions) run in their own single-call wave.
    - Preserves execution dependencies while maximizing parallelism.
    """
    waves: list[list[ToolCall]] = []
    current_wave: list[ToolCall] = []
    current_wave_write_paths: set[str] = set()
    current_wave_read_paths: set[str] = set()
    current_has_barrier = False

    for call in calls:
        name = call.name
        is_barrier = name in BARRIER_TOOLS
        is_read_only = name in READ_ONLY_TOOLS
        is_file_write = name in ("write_file", "edit_file", "replace_file_content", "multi_replace_file_content")
        target_path = str(call.arguments.get("file_path", "") or call.arguments.get("target_file", "")).strip()

        if not current_wave:
            current_wave.append(call)
            if is_barrier:
                current_has_barrier = True
            elif is_read_only:
                if target_path:
                    current_wave_read_paths.add(target_path)
            elif is_file_write and target_path:
                current_wave_write_paths.add(target_path)
            continue

        if is_barrier or current_has_barrier:
            waves.append(current_wave)
            current_wave = [call]
            current_wave_write_paths = {target_path} if is_file_write and target_path else set()
            current_wave_read_paths = {target_path} if is_read_only and target_path else set()
            current_has_barrier = is_barrier
            continue

        if is_read_only:
            if target_path and target_path in current_wave_write_paths:
                waves.append(current_wave)
                current_wave = [call]
                current_wave_write_paths = set()
                current_wave_read_paths = {target_path}
                current_has_barrier = False
            else:
                current_wave.append(call)
                if target_path:
                    current_wave_read_paths.add(target_path)
            continue

        if is_file_write:
            if target_path and (target_path in current_wave_write_paths or target_path in current_wave_read_paths):
                waves.append(current_wave)
                current_wave = [call]
                current_wave_write_paths = {target_path}
                current_wave_read_paths = set()
                current_has_barrier = False
            else:
                current_wave.append(call)
                if target_path:
                    current_wave_write_paths.add(target_path)
            continue

        waves.append(current_wave)
        current_wave = [call]
        current_wave_write_paths = set()
        current_wave_read_paths = set()
        current_has_barrier = False

    if current_wave:
        waves.append(current_wave)

    return waves


def format_tool_action_label(name: str, args: dict[str, Any]) -> str:
    """Formats a concise lowercase action string such as 'inspecting file'."""
    if name == "read_file":
        fp = str(args.get("file_path", "")).strip()
        return f"inspecting {fp}" if fp else "inspecting file"
    if name == "list_directory":
        path = str(args.get("directory_path", "") or args.get("path", ".")).strip()
        return f"inspecting {path}/" if path and path != "." else "inspecting directory"
    if name == "grep_search":
        q = str(args.get("query", "")).strip()
        return f"searching for '{q[:30]}'" if q else "searching files"
    if name == "edit_file":
        fp = str(args.get("file_path", "")).strip()
        return f"updating {fp}" if fp else "updating file"
    if name == "write_file":
        fp = str(args.get("file_path", "")).strip()
        return f"creating {fp}" if fp else "creating file"
    if name == "run_terminal_command":
        cmd = str(args.get("command", "")).strip()
        return f"running command {cmd[:45]}" if cmd else "running command"
    if name == "spawn_subagent":
        role = str(args.get("role", "")).strip()
        return f"delegating to {role} subagent" if role else "delegating to subagent"
    if name == "spawn_parallel_subagents":
        sub_list = args.get("subagents", [])
        count = len(sub_list) if isinstance(sub_list, list) else 1
        return f"running {count} subagents in parallel"
    if name == "read_skill":
        sn = str(args.get("skill_name", "")).strip()
        return f"reading skill {sn}" if sn else "reading skill"
    if name == "list_skills":
        return "listing available skills"
    if name == "save_memory":
        key = str(args.get("key", "")).strip()
        return f"saving memory '{key}'" if key else "saving memory"
    if name == "read_memory":
        key = str(args.get("key", "")).strip()
        return f"recalling memory '{key}'" if key else "recalling memory"
    if name == "git_status":
        return "checking git status"
    if name == "git_diff":
        return "checking git diff"
    if name == "git_commit":
        msg = str(args.get("message", "")).strip()
        return f"committing git changes: {msg[:30]}" if msg else "committing git changes"
    if name == "git_push":
        return "pushing to remote"
    if name == "todo_write":
        todos = args.get("todos", [])
        count = len(todos) if isinstance(todos, list) else 1
        return f"updating task list ({count} items)"
    if name == "exit_plan_mode":
        return "submitting implementation plan & exiting plan mode"
    return f"executing {name}"


def _format_tool_substep(name: str, args: dict[str, Any]) -> str:
    action = format_tool_action_label(name, args)
    return f"[tool call] {action}"


def explicitly_requested_reusable_tool(user_request: str) -> bool:
    """Only allow persistent tool-catalog changes when the user asked for one."""
    request = str(user_request or "").lower().replace("_", " ")
    action = r"\b(?:create|add|build|make|implement|register|forge)\b"
    tool = r"\b(?:(?:a|an|the|new|custom|reusable|kratos|agent|general-purpose)\s+){0,4}tool\b"
    return bool(
        re.search(action + r"\s+" + tool, request)
        or re.search(r"\b(?:self tool creator|custom tool|reusable tool|new tool)\b", request)
    )


def user_requested_artifact(user_request: str) -> bool:
    request = str(user_request or "").lower()
    asks_to_create = re.search(r"\b(?:create|build|make|write|generate|implement|finish|complete)\b", request)
    names_artifact = re.search(r"\b(?:website|web\s?page|site|app|application|file|report|deliverable|component|script|project)\b", request)
    return bool(asks_to_create and names_artifact)


def _format_tool_result_substep(name: str, args: dict[str, Any], content: str) -> str:
    if name == "write_file":
        fp = str(args.get("file_path", "")).strip()
        return f"[tool call] created {fp}" if fp else "[tool call] created file"
    if name == "edit_file":
        fp = str(args.get("file_path", "")).strip()
        return f"[tool call] updated {fp}" if fp else "[tool call] updated file"
    if name == "read_file":
        fp = str(args.get("file_path", "")).strip()
        return f"[tool call] inspected {fp}" if fp else "[tool call] inspected file"
    if name == "list_directory":
        return "[tool call] inspected directory"
    if name == "grep_search":
        return "[tool call] search completed"
    if name == "run_terminal_command":
        cmd = str(args.get("command", "")).strip()
        return f"[tool call] ran {cmd[:45]}" if cmd else "[tool call] command executed"
    if name == "spawn_subagent":
        role = str(args.get("role", "")).strip()
        return f"[tool call] completed {role} subagent" if role else "[tool call] completed subagent"
    if name == "spawn_parallel_subagents":
        sub_list = args.get("subagents", [])
        count = len(sub_list) if isinstance(sub_list, list) else 1
        return f"[tool call] completed {count} parallel subagents"
    if name == "read_skill":
        sn = str(args.get("skill_name", "")).strip()
        return f"[tool call] loaded skill {sn}" if sn else "[tool call] loaded skill"
    if name == "list_skills":
        return "[tool call] listed available skills"
    if name == "save_memory":
        return "[tool call] saved memory"
    if name == "read_memory":
        return "[tool call] recalled memory"
    if name == "git_status":
        return "[tool call] checked git status"
    if name == "git_diff":
        return "[tool call] checked git diff"
    if name == "git_commit":
        return "[tool call] committed git changes"
    if name == "git_push":
        return "[tool call] pushed to remote"
    if name == "todo_write":
        return "[tool call] updated todo list"
    if name == "exit_plan_mode":
        return "[tool call] plan submitted"
    return f"[tool call] completed {name}"


def _extract_target_dir_and_deliverables(query: str, workspace: Path) -> tuple[str | None, list[str]]:
    """Parses target workspace directory and expected output deliverables from user query."""
    target_dir = None
    deliverables: list[str] = []

    # 1. Detect explicit directory in quotes or Windows drive path:
    win_quoted_m = re.search(r'["\']([a-zA-Z]:[/\\][^"\'*?<>|\r\n]+)["\']', query)
    if win_quoted_m:
        raw_path = win_quoted_m.group(1).strip()
        if not re.search(r'\.[a-zA-Z0-9]+$', raw_path):
            target_dir = raw_path.replace("\\", "/")
    else:
        win_unquoted_m = re.search(r'(?<![a-zA-Z0-9_])([a-zA-Z]:[/\\][^\s"\'*?<>|\r\n]+)', query)
        if win_unquoted_m:
            raw_path = win_unquoted_m.group(1).strip()
            if not re.search(r'\.[a-zA-Z0-9]+$', raw_path):
                target_dir = raw_path.replace("\\", "/")

    # 2. Detect requested deliverable output files:
    folder_named_m = re.search(
        r'(?:stored|saved|written)\s+in\s+(?:the\s+|same\s+)?([a-zA-Z0-9_-]+)\s+folder\s+named\s+as\s+([a-zA-Z0-9_.-]+)',
        query,
        re.IGNORECASE,
    )
    if folder_named_m:
        folder = folder_named_m.group(1).strip()
        fname = folder_named_m.group(2).strip()
        deliverables.append(f"{folder}/{fname}")

    named_m = re.search(r'(?:named\s+as|named)\s+([a-zA-Z0-9_.-]+\.[a-zA-Z0-9]+)', query, re.IGNORECASE)
    if named_m:
        fn = named_m.group(1).strip()
        if not any(d.endswith(fn) for d in deliverables):
            deliverables.append(fn)

    saved_m = re.search(r'(?:stored|saved|written)\s+(?:as|in|to)\s+([a-zA-Z0-9_./\\-]+\.[a-zA-Z0-9]+)', query, re.IGNORECASE)
    if saved_m:
        sp = saved_m.group(1).strip().replace("\\", "/")
        if sp not in deliverables:
            deliverables.append(sp)

    clean_deliverables = []
    for d in deliverables:
        d_norm = d.replace("\\", "/").strip().lstrip("/")
        if d_norm and d_norm not in clean_deliverables:
            clean_deliverables.append(d_norm)

    return target_dir, clean_deliverables


def _is_no_task_hallucination(text: str) -> bool:
    """Detects when the model falsely claims there is no task or asks what to do."""
    if not text:
        return False
    t = text.lower()
    indicators = [
        "no task in your last message",
        "no task in your message",
        "there is no task in your",
        "there is no task",
        "there's no task",
        "nothing to execute yet",
        "nothing to execute",
        "so there's nothing to execute",
        "so there is nothing to execute",
        "give me the actual request",
        "please provide a task",
        "no task provided",
        "nothing for me to execute",
    ]
    return any(ind in t for ind in indicators)


def _verify_deliverables(deliverables: list[str], target_dir: str | None, workspace: Path) -> tuple[bool, list[str], list[str]]:
    """Checks if all target deliverables exist on disk and are non-empty."""
    existing = []
    missing = []
    for d in deliverables:
        candidates = [
            workspace / d,
            Path(d),
        ]
        if target_dir:
            candidates.append(Path(target_dir) / d)

        found = False
        for c in candidates:
            try:
                if c.is_file() and c.stat().st_size > 0:
                    found = True
                    existing.append(str(c))
                    break
            except Exception as exc:
                logger.debug("Operation error suppressed: %s", exc)
        if not found:
            missing.append(d)
    return len(missing) == 0, existing, missing


class AgentLoop:
    def __init__(
        self,
        context: ContextBuilder,
        instructions: Any,
        tools: Any,
        model: Any,
        emit: Callable[[RuntimeEvent], None],
        workspace: Path,
        cancellation_flag: threading.Event | None = None,
    ) -> None:
        self.context = context
        self.instructions = instructions
        self.tools = tools
        self.model = model
        self.emit_fn = emit
        self.workspace = workspace.resolve()
        self.tool_platform = "windows" if os.name == "nt" else "linux"
        self.tool_cwd = str(self.workspace)
        self.cancellation_flag: threading.Event = cancellation_flag or threading.Event()

        self.workspace_tracker = WorkspaceTracker(self.workspace)
        self.verification_manager = VerificationManager(self.workspace, self.emit)
        self.terminal_latch = TerminalLatch()
        self.current_plan: ExecutionPlan | None = None
        self.last_verification: VerificationResult | None = None
        self.current_run: AgentRunState | None = None
        self._current_turn_id: str = ""
        self.on_speech: Callable[[str], None] | None = None

        # Wire dynamic todo_write and exit_plan_mode tool handlers
        try:
            from kratos_agent.utils.tools import set_plan_mode_handler, set_todo_handler
            set_todo_handler(self._on_todo_update)
            set_plan_mode_handler(self._on_plan_mode_exit)
        except Exception as exc:
            logger.debug("Operation error suppressed: %s", exc)

    def _tool_schemas(self, context: str, categories: list[str] | None) -> list[dict[str, Any]]:
        """Call context-aware registries while preserving the legacy schemas() contract."""
        schema_method = self.tools.schemas
        try:
            parameters = inspect.signature(schema_method).parameters
        except (TypeError, ValueError):
            parameters = {}
        accepts_kwargs = any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
        kwargs: dict[str, Any] = {}
        if "context" in parameters or accepts_kwargs:
            kwargs["context"] = context
        if "categories" in parameters or accepts_kwargs:
            kwargs["categories"] = categories
        return schema_method(**kwargs)

    def _check_task_completion_gate(self, task: TaskItem, turn_id: str) -> tuple[bool, str | None]:
        """Checks completion gate for a task. Returns (allowed, correction)."""
        if not getattr(task, "requires_observable_evidence", False):
            return True, None

        ccs = getattr(self.tools, "ccs", None) or getattr(self.tools, "_ccs", None)
        if not ccs:
            try:
                from kratos_agent.ccs import get_controller
                ccs = get_controller()
            except Exception:
                ccs = None

        evidence = getattr(task, "observed_evidence", None)
        if (evidence is None or not getattr(evidence, "trustworthy", False)) and getattr(task, "assertion", None):
            evidence = self.verification_manager.verify_observable_outcome(task.assertion, ccs)
            task.observed_evidence = evidence

        verdict = self.verification_manager.gate_completion(task, {"title": task.title}, evidence)
        if verdict.allow:
            return True, None

        # Rejected by gate!
        attempts = getattr(task, "_completion_attempts", 0) + 1
        task._completion_attempts = attempts

        if attempts < 3:
            self.emit(RuntimeEvent(
                EventKind.FALSE_COMPLETION,
                {
                    "task_id": task.id,
                    "claimed": {"title": task.title},
                    "observed": evidence.to_model_dict() if evidence and hasattr(evidence, "to_model_dict") else None,
                    "attempt": attempts,
                    "retries_left": 3 - attempts,
                    "correction": verdict.correction,
                },
                turn_id,
            ))
            return False, verdict.correction
        else:
            task.fail(verdict.correction)
            if self.terminal_latch.try_set(task.id, "FAILED"):
                self.emit(RuntimeEvent(
                    EventKind.TASK_FAILED,
                    {
                        **task.to_dict(),
                        "honest_failure": True,
                        "evidence": evidence.to_model_dict() if evidence and hasattr(evidence, "to_model_dict") else None,
                        "reason": evidence.detail if evidence and hasattr(evidence, "detail") else verdict.correction,
                    },
                    turn_id,
                ))
            return False, None

    def _collect_browser_evidence(self) -> list[Any]:
        """Re-run declared browser assertions against live state before turn completion."""
        if not self.current_plan:
            return []
        browser_tasks = [
            task for task in self.current_plan.tasks
            if "browser" in str(getattr(task, "verification", "")).lower()
        ]
        if not browser_tasks:
            return []
        ccs = getattr(self.tools, "ccs", None) or getattr(self.tools, "_ccs", None)
        if not ccs:
            try:
                from kratos_agent.ccs import get_controller
                ccs = get_controller()
            except Exception:
                ccs = None
        evidence: list[Any] = []
        for task in browser_tasks:
            assertion = getattr(task, "assertion", None)
            if assertion is None:
                continue
            try:
                observed = self.verification_manager.verify_observable_outcome(assertion, ccs)
            except Exception as exc:
                logger.debug("Browser assertion failed for %s: %s", task.title, type(exc).__name__)
                continue
            task.observed_evidence = observed
            evidence.append(observed)
        return evidence

    def _on_todo_update(self, todos: list) -> None:
        """Handles whole-list todo updates from todo_write tool call."""
        from kratos_agent.core.task_manager import (
            AgentState,
            ExecutionPlan,
            TaskItem,
            TaskState,
        )

        task_items: list[TaskItem] = []
        for i, item in enumerate(todos):
            content = str(item.get("content", f"Task {i+1}")).strip()
            status = str(item.get("status", "pending")).lower()
            if status == "completed":
                state = TaskState.COMPLETED
            elif status in ("in_progress", "running"):
                state = TaskState.RUNNING
            else:
                state = TaskState.PENDING
            task_item = TaskItem(
                id=f"todo_{i+1}",
                title=content,
                state=state,
            )
            if state == TaskState.COMPLETED:
                task_item.complete("Completed by agent")
            task_items.append(task_item)

        if not self.current_plan:
            self.current_plan = ExecutionPlan(goal="Agent Plan", tasks=task_items, title="TODO LIST")
        else:
            self.current_plan.tasks = task_items

        self.current_plan.state = AgentState.EXECUTING
        turn_id = getattr(self, "_current_turn_id", "") or "todo_sync"
        self.emit(RuntimeEvent(EventKind.PLAN_CREATED, self.current_plan.to_dict(), turn_id))

    def _on_plan_mode_exit(self, plan: str) -> None:
        """Handles plan submission and exit from plan mode."""
        turn_id = getattr(self, "_current_turn_id", "") or "plan_exit"
        self.emit(RuntimeEvent(EventKind.PLAN_CREATED, {"plan_markdown": plan, "status": "submitted"}, turn_id))

    def emit(self, event: RuntimeEvent) -> None:
        """Emits event through both the direct callback and the global EventBus."""
        try:
            self.emit_fn(event)
        except Exception as exc:
            logger.debug("Operation error suppressed: %s", exc)
        try:
            event_bus.publish(event)
        except Exception as exc:
            logger.debug("Operation error suppressed: %s", exc)

    def cancel(self) -> None:
        """Signal this loop to cancel at the next tool boundary."""
        self.cancellation_flag.set()

    def clear_cancel(self) -> None:
        """Clear any pending cancellation signal."""
        self.cancellation_flag.clear()

    def _execute_tool_call_worker(
        self,
        call: ToolCall,
        allow_tool: Callable[[Any, dict[str, Any]], tuple[bool, str]],
    ) -> ToolResult:
        """Executes a single tool call and prunes its result text."""
        try:
            if (
                call.name in ARTIFACT_INSPECTION_TOOLS
                and self.current_run is not None
                and user_requested_artifact(self.current_run.user_request)
                and not self.current_run.written_files
            ):
                inspections = sum(
                    item.get("name") in ARTIFACT_INSPECTION_TOOLS
                    for item in self.current_run.completed_tools
                )
                if inspections >= 12:
                    return ToolResult(
                        call_id=call.call_id,
                        name=call.name,
                        content=(
                            "Inspection loop limit reached: stop searching and create the requested deliverable "
                            "with the existing write_file/edit_file tools using the information already inspected."
                        ),
                        is_error=True,
                    )
            if call.name == "run_terminal_command" and self.current_run is not None:
                command = str(call.arguments.get("command", "")).strip()
                previously_failed = any(
                    item.get("name") == call.name
                    and item.get("is_error")
                    and str((item.get("args") or {}).get("command", "")).strip() == command
                    for item in self.current_run.completed_tools
                )
                if previously_failed:
                    return ToolResult(
                        call_id=call.call_id,
                        name=call.name,
                        content=(
                            "Repeated identical failed command blocked. Do not retry it unchanged. "
                            "Use the error output to correct the command or use an appropriate existing tool."
                        ),
                        is_error=True,
                    )
            if (
                call.name == "self_tool_creator"
                and self.current_run is not None
                and not explicitly_requested_reusable_tool(self.current_run.user_request)
            ):
                return ToolResult(
                    call_id=call.call_id,
                    name=call.name,
                    content=(
                        "Rejected self_tool_creator: this changes Kratos's persistent source and tool catalog. "
                        "The user's task did not request a reusable Kratos tool. Use existing workspace tools "
                        "such as write_file/edit_file, then verify the deliverable."
                    ),
                    is_error=True,
                )
            result = self.tools.execute(call, allow_tool)
            # If writing a relative deliverable and target_dir is configured, mirror to target_dir as well
            if not result.is_error and call.name in ("write_file", "edit_file") and self.current_run and self.current_run.target_dir:
                fp = str(call.arguments.get("file_path", "")).strip()
                if fp and not (Path(fp).is_absolute() or re.match(r'^[a-zA-Z]:', fp)):
                    try:
                        target_fp = Path(self.current_run.target_dir) / fp
                        target_fp.parent.mkdir(parents=True, exist_ok=True)
                        content = str(call.arguments.get("content", ""))
                        if content:
                            target_fp.write_text(content, encoding="utf-8")
                    except Exception as exc:
                        logger.debug("Operation error suppressed: %s", exc)
            output, truncated = self.context.prune_tool_result(result.content)
            result.content, result.truncated = output, truncated
            return result
        except Exception as exc:
            return ToolResult(
                call_id=call.call_id,
                name=call.name,
                content=f"Error during parallel tool execution: {type(exc).__name__}: {exc}",
                is_error=True,
                truncated=False,
            )


    def _track_tool_side_effects(self, name: str, args: dict[str, Any], is_error: bool, turn_id: str) -> None:
        fp = str(args.get("file_path", "") or args.get("path", "") or args.get("target_file", "")).strip()

        if self.current_run:
            self.current_run.record_tool_call(name, args, is_error)

        if name == "write_file":
            if not is_error and fp:
                self.workspace_tracker.record_file_created(fp)
                if self.current_run:
                    self.current_run.record_written_file(fp)
                self.emit(RuntimeEvent(EventKind.FILE_CREATED, {"file_path": fp}, turn_id))
        elif name in ("edit_file", "replace_file_content", "multi_replace_file_content"):
            if not is_error and fp:
                self.workspace_tracker.record_file_modified(fp)
                if self.current_run:
                    self.current_run.record_written_file(fp)
                self.emit(RuntimeEvent(EventKind.FILE_MODIFIED, {"file_path": fp}, turn_id))
        elif name in ("read_file", "list_directory", "grep_search", "search_symbol", "read_symbol", "view_outline"):
            if fp:
                self.workspace_tracker.record_file_inspected(fp)
                if self.current_run:
                    self.current_run.record_inspected_file(fp)
                self.emit(RuntimeEvent(EventKind.FILE_INSPECTED, {"file_path": fp}, turn_id))
        elif name in ("run_terminal_command", "computer_launch"):
            cmd = str(args.get("command", "") or args.get("target", "") or " ".join(str(x) for x in args.get("args", []))).strip()
            if cmd:
                self.workspace_tracker.record_command(cmd, 1 if is_error else 0)
                if self.current_run:
                    self.current_run.record_command(cmd)
                if not is_error:
                    created_targets = []
                    for target in re.findall(r'(?:Set-Content|Out-File)\s+(?:-Path\s+)?["\']?([^"\'\s>|]+\.[a-zA-Z0-9]+)["\']?', cmd, re.IGNORECASE):
                        created_targets.append(target)
                    for target in re.findall(r'(?:>|>>)\s*["\']?([a-zA-Z0-9_./\\-]+\.[a-zA-Z0-9]+)["\']?', cmd):
                        created_targets.append(target)
                    for target in created_targets:
                        self.workspace_tracker.record_file_created(target)
                        if self.current_run:
                            self.current_run.record_written_file(target)
                        self.emit(RuntimeEvent(EventKind.FILE_CREATED, {"file_path": target}, turn_id))
                self.emit(RuntimeEvent(EventKind.COMMAND_COMPLETED, {"command": cmd, "is_error": is_error}, turn_id))

    def run(
        self,
        history: list[ChatMessage],
        allow_tool: Callable[..., tuple[bool, str]],
        max_steps: int | None = None,
        resume_plan: ExecutionPlan | None = None,
    ) -> tuple[str, list[ChatMessage]]:
        turn_id = uuid.uuid4().hex
        self._current_turn_id = turn_id
        self.workspace_tracker.reset()
        self.last_verification = None

        profiler = reset_active_profiler()
        router = get_request_router()

        # 1. Identify User Prompt & Intent
        user_query = ""
        for m in reversed(history):
            if m.role == "user":
                user_query = m.content
                break

        with profiler.measure("route"):
            route_decision = router.classify(user_query, history)

        is_continue = user_query.strip().lower() in ("continue", "resume", "/continue")
        if route_decision.is_fast_path and not route_decision.requires_planning:
            intent = IntentKind.CHAT if route_decision.category in (RequestCategory.CHAT, RequestCategory.CODE, RequestCategory.TOOL) else IntentKind.QUESTION
        else:
            intent = IntentKind.CODING_TASK if is_continue else classify_intent(user_query, history)

        # Initialize or maintain stable AgentRunState across turns and model calls
        target_dir, deliverables = _extract_target_dir_and_deliverables(user_query, self.workspace)
        run_id = f"kratos_run_{turn_id[:8]}"
        if not is_continue or not self.current_run:
            self.current_run = AgentRunState(
                run_id=run_id,
                user_request=user_query,
                workspace=str(self.workspace),
                target_dir=target_dir,
                target_deliverables=deliverables,
            )
        else:
            if target_dir and not self.current_run.target_dir:
                self.current_run.target_dir = target_dir
            if deliverables:
                for d in deliverables:
                    if d not in self.current_run.target_deliverables:
                        self.current_run.target_deliverables.append(d)

        self.emit(RuntimeEvent(
            EventKind.AGENT_STARTED,
            {"query": user_query, "intent": intent.value, "is_continue": is_continue},
            turn_id,
        ))
        self.emit(RuntimeEvent(EventKind.TURN_STARTED, {"message_count": len(history), "intent": intent.value}, turn_id))

        # 2. Phased Planning
        if is_continue and resume_plan:
            self.current_plan = resume_plan
            self.current_plan.state = AgentState.EXECUTING
            # Reset any interrupted tasks to pending
            for t in self.current_plan.tasks:
                if t.state == TaskState.NEEDS_ATTENTION:
                    t.state = TaskState.PENDING
            # Activate first unfinished task
            active = self.current_plan.get_active_task() or (self.current_plan.get_pending_tasks()[0] if self.current_plan.get_pending_tasks() else None)
            if active:
                active.start()
            self.emit(RuntimeEvent(EventKind.AGENT_RESUMED, {"plan": self.current_plan.to_dict()}, turn_id))
        elif intent.requires_plan:
            self.emit(RuntimeEvent(EventKind.UNDERSTANDING_STARTED, {"query": user_query}, turn_id))
            self.emit(RuntimeEvent(EventKind.PLANNING_STARTED, {"query": user_query}, turn_id))

            # Invoke the Agent/LLM to produce the dynamic structured plan
            instructions_built = self.instructions.build() if hasattr(self.instructions, "build") else None
            self.current_plan = formulate_agent_plan(
                user_query=user_query,
                model=self.model,
                workspace=self.workspace,
                instructions=instructions_built,
            )

            if self.current_plan and self.current_plan.tasks:
                self.current_plan.state = AgentState.PLANNING
                self.emit(RuntimeEvent(EventKind.PLAN_CREATED, self.current_plan.to_dict(), turn_id))

                self.current_plan.state = AgentState.EXECUTING
                # Activate task 1
                t1 = self.current_plan.tasks[0]
                t1.start()
                self.emit(RuntimeEvent(EventKind.TASK_STARTED, t1.to_dict(), turn_id))
        else:
            self.current_plan = None

        conversational_nudge_count = 0

        # 3. Execution Phase Loop
        step = 0
        while max_steps is None or step < max_steps:
            step += 1
            # Check cancellation flag
            if self.cancellation_flag.is_set():
                if self.current_plan:
                    self.current_plan.pause_running_tasks("Interrupted by user")
                    self.emit(RuntimeEvent(EventKind.AGENT_PAUSED, {"plan": self.current_plan.to_dict()}, turn_id))
                message = "Agent execution was interrupted."
                self.emit(RuntimeEvent(EventKind.TURN_FAILED, {"error": "cancelled", "plan": self.current_plan.to_dict() if self.current_plan else None}, turn_id))
                profiler.finish()
                return message, history

            # Assemble Context & Request with active run_state and dynamic tool filtering
            built = self.context.assemble(
                self.instructions.build(),
                history,
                self._tool_schemas(
                    user_query,
                    route_decision.target_tool_categories if route_decision.target_tool_categories else None,
                ),
                {"cwd": self.tool_cwd, "platform": self.tool_platform},
                run_state=self.current_run,
            )
            if built["compaction"]:
                self.emit(RuntimeEvent(EventKind.COMPACTED, built["compaction"], turn_id))
            request = built["request"]
            self.emit(RuntimeEvent(EventKind.REQUEST_ASSEMBLED, _redacted_request(request), turn_id))

            # Complete Model Request
            stream_filter = DirectiveStreamFilter()

            def _handle_chunk(chunk: str) -> None:
                visible_chunk = stream_filter.push(chunk)
                if visible_chunk:
                    self.emit(RuntimeEvent(EventKind.MODEL_CHUNK, {"chunk": visible_chunk}, turn_id))

            try:
                with profiler.measure("llm"):
                    try:
                        response = self.model.complete(request, on_chunk=_handle_chunk)
                    except TypeError as type_err:
                        if "unexpected keyword argument 'on_chunk'" in str(type_err) or "got an unexpected keyword" in str(type_err):
                            response = self.model.complete(request)
                        else:
                            raise
                stream_filter.flush()
            except Exception as exc:
                stream_filter.flush()
                if self.current_plan:
                    active = self.current_plan.get_active_task()
                    if active:
                        active.fail(str(exc))
                self.emit(RuntimeEvent(EventKind.TURN_FAILED, {"error": f"{type(exc).__name__}: {exc}"}, turn_id))
                profiler.finish()
                return f"Model request failed: {exc}", history

            self.emit(RuntimeEvent(
                EventKind.MODEL_RESPONSE,
                {
                    "finish_reason": response.finish_reason,
                    "usage": response.usage,
                    "tool_calls": [call.__dict__ for call in response.tool_calls],
                },
                turn_id,
            ))

            # Handle Case Where Model Produced No Tool Calls
            directive = extract_speech_directives(response.text)
            if not response.tool_calls:
                final_text = directive.display_text.strip()

                # 1. Anti-Hallucination Guard: Intercept "no task in your message" responses
                if _is_no_task_hallucination(final_text) and self.current_run and (self.current_run.completed_tools or self.current_run.target_deliverables or intent != IntentKind.CHAT) and conversational_nudge_count < 5:
                    conversational_nudge_count += 1
                    history.append(ChatMessage(role="assistant", content=final_text))
                    nudge_text = (
                        f"[RUNTIME CORRECTION - ACTIVE TASK IN PROGRESS]\n"
                        f"The user task is actively running. DO NOT abort, do not claim there is no task, and do not reference past unrelated projects.\n\n"
                        f"ACTIVE USER OBJECTIVE:\n"
                        f"\"{self.current_run.user_request}\"\n\n"
                        f"CURRENT STATE:\n"
                        f"- Inspected Files: {len(self.current_run.inspected_files)} ({', '.join(self.current_run.inspected_files[-8:]) if self.current_run.inspected_files else 'None'})\n"
                        f"- Written Deliverables: {len(self.current_run.written_files)} ({', '.join(self.current_run.written_files) if self.current_run.written_files else 'None'})\n"
                        f"- Target Deliverables: {', '.join(self.current_run.target_deliverables) if self.current_run.target_deliverables else 'Complete analysis and report'}\n\n"
                        f"ACTION REQUIRED:\n"
                        f"Proceed immediately with analyzing the findings and generating the requested deliverables. "
                        f"Call `write_file` now to produce the deliverable report."
                    )
                    history.append(ChatMessage(role="user", content=nudge_text))
                    continue

                # 2. Deliverable Verification Guard: Ensure requested output files exist on disk before completing
                if self.current_run and self.current_run.target_deliverables and conversational_nudge_count < 5:
                    all_exist, existing_files, missing_files = _verify_deliverables(
                        self.current_run.target_deliverables,
                        self.current_run.target_dir,
                        self.workspace,
                    )
                    if not all_exist:
                        conversational_nudge_count += 1
                        history.append(ChatMessage(role="assistant", content=final_text or "Continuing execution..."))
                        nudge_text = (
                            "[RUNTIME VERIFICATION REQUIRED]: The following requested deliverable file(s) have NOT been created on disk yet:\n"
                            + "\n".join(f"- {m}" for m in missing_files) + "\n\n"
                            "You must now invoke `write_file` to write the required report/deliverable to disk. "
                            "Do NOT stop or return conversational monologue until the file has been written."
                        )
                        history.append(ChatMessage(role="user", content=nudge_text))
                        continue

                # If we have an active plan with unfinished tasks, check if tools are needed or verification applies
                if self.current_plan and self.current_plan.tasks:
                    # 4. Dedicated Verification Phase
                    self.current_plan.state = AgentState.VERIFYING
                    changed = list(self.workspace_tracker.all_changed_files)
                    if not changed and self.current_run and self.current_run.written_files:
                        changed = list(self.current_run.written_files)

                    verif_types = [t.verification for t in self.current_plan.tasks if getattr(t, "verification", "none") != "none"]
                    verif_type = "+".join(sorted(set(verif_types))) if verif_types else "auto"

                    goal_lower = str(self.current_plan.goal or user_query).lower()
                    has_mutation_verbs = any(kw in goal_lower for kw in ("create", "build", "scaffold", "website", "webapp", "app", "implement", "make", "develop", "write", "generate", "code"))
                    is_read_only_goal = any(kw in goal_lower for kw in ("read", "check", "inspect", "what is", "tell me", "explain", "find", "show", "search", "version")) and not has_mutation_verbs
                    is_mutation_task = has_mutation_verbs or any(any(kw in t.title.lower() for kw in ("create", "write", "edit", "modify", "scaffold", "html", "webapp", "build", "implement", "develop", "setup", "install", "add", "make", "generate", "code")) for t in self.current_plan.tasks)
                    require_files = not is_read_only_goal and (is_mutation_task or len(self.workspace_tracker.created_files) > 0 or len(self.workspace_tracker.modified_files) > 0)
                    browser_evidence = self._collect_browser_evidence()
                    self.last_verification = self.verification_manager.verify_workspace(
                        changed,
                        verification_type=verif_type,
                        require_files=require_files,
                        browser_evidence=browser_evidence,
                        turn_id=turn_id,
                    )

                    # Check completion gate on any tasks requiring observable evidence
                    evidence_gate_blocked = False
                    for t in self.current_plan.tasks:
                        if getattr(t, "requires_observable_evidence", False) and t.state != TaskState.COMPLETED:
                            allowed, correction = self._check_task_completion_gate(t, turn_id)
                            if not allowed and correction:
                                history.append(ChatMessage(role="assistant", content=final_text or "Checking task outcome..."))
                                history.append(ChatMessage(role="user", content=f"[RUNTIME VERIFICATION FAILED - {t.title}]: {correction}"))
                                conversational_nudge_count += 1
                                evidence_gate_blocked = True
                                break
                    if evidence_gate_blocked:
                        continue

                    has_created_deliverables = bool(
                        changed
                        or (self.current_run and self.current_run.written_files)
                        or len(self.workspace_tracker.created_files) > 0
                        or len(self.workspace_tracker.modified_files) > 0
                    )

                    # If verification passed and files were validated, fulfill all verified tasks with evidence
                    if (self.last_verification and self.last_verification.passed and self.last_verification.files_checked > 0) or has_created_deliverables:
                        files_count = self.last_verification.files_checked if (self.last_verification and self.last_verification.files_checked > 0) else len(changed)
                        for t in self.current_plan.tasks:
                            if t.state in (TaskState.PENDING, TaskState.RUNNING):
                                if getattr(t, "requires_observable_evidence", False):
                                    allowed, _ = self._check_task_completion_gate(t, turn_id)
                                    if not allowed:
                                        continue
                                t.add_evidence("verification", {"files_checked": files_count})
                                t.complete(f"Verified {files_count} file(s)")
                                if self.terminal_latch.try_set(t.id, "COMPLETED"):
                                    self.emit(RuntimeEvent(EventKind.TASK_COMPLETED, t.to_dict(), turn_id))
                    elif self.last_verification and self.last_verification.passed and is_read_only_goal:
                        for t in self.current_plan.tasks:
                            if t.state != TaskState.COMPLETED:
                                t.complete("Completed")
                                if self.terminal_latch.try_set(t.id, "COMPLETED"):
                                    self.emit(RuntimeEvent(EventKind.TASK_COMPLETED, t.to_dict(), turn_id))

                    # Check unfinished tasks after verification
                    remaining_unfinished = self.current_plan.get_unfinished_tasks()

                    # Detect if the model stated completion or delivered final output
                    final_text_lower = final_text.lower()
                    model_claims_done = any(w in final_text_lower for w in (
                        "status: ✅ completed", "status: completed", "completed", "all files written",
                        "created a complete", "files written", "all three write", "successfully created",
                        "task completed", "finished", "here is the", "here are the"
                    ))

                    # If deliverables were created or model delivered the final answer, complete remaining non-failing tasks
                    if remaining_unfinished and (has_created_deliverables or model_claims_done):
                        for ut in remaining_unfinished:
                            ut.complete("Completed with final deliverables")
                            if self.terminal_latch.try_set(ut.id, "COMPLETED"):
                                self.emit(RuntimeEvent(EventKind.TASK_COMPLETED, ut.to_dict(), turn_id))
                        remaining_unfinished = []

                    # Auto-continue: Only nudge if genuinely unfinished with zero deliverables and no completion stated
                    if remaining_unfinished and not has_created_deliverables and not model_claims_done and conversational_nudge_count < 2:
                        next_task = remaining_unfinished[0]
                        if next_task.state == TaskState.PENDING:
                            next_task.start()
                            self.emit(RuntimeEvent(EventKind.TASK_STARTED, next_task.to_dict(), turn_id))

                        history.append(ChatMessage(role="assistant", content=final_text or "Continuing execution..."))
                        history.append(ChatMessage(
                            role="user",
                            content=(
                                f"[System Directive - Auto-Continue]: Plan task '{next_task.title}' is pending ({len(remaining_unfinished)} tasks remaining). "
                                + (f"You stated: '{final_text[:120]}'. " if final_text else "") +
                                "Do NOT stop or output conversational text without tool calls. "
                                "Immediately invoke the required tools (`run_terminal_command`, `write_file`, `edit_file`, etc.) to execute this task now."
                            )
                        ))
                        conversational_nudge_count += 1
                        continue

                    # Only complete overall plan if all tasks are COMPLETED and verification passed
                    all_done = (len(remaining_unfinished) == 0 and len(self.current_plan.tasks) > 0)
                    if self.last_verification.passed and all_done:
                        self.current_plan.state = AgentState.COMPLETED
                        run_id = self.current_run.run_id if self.current_run else turn_id
                        if self.terminal_latch.try_set(run_id, "COMPLETED"):
                            self.emit(RuntimeEvent(
                                EventKind.AGENT_COMPLETED,
                                {
                                    "goal": self.current_plan.goal,
                                    "plan": self.current_plan.to_dict(),
                                    "files_changed": self.workspace_tracker.summary(),
                                    "verification": self.last_verification.__dict__,
                                    "final": final_text,
                                },
                                turn_id,
                            ))
                    else:
                        self.current_plan.state = AgentState.FAILED
                        for ut in remaining_unfinished:
                            if ut.state != TaskState.FAILED:
                                ut.fail("Task was not executed or lacked completion evidence.")
                                if self.terminal_latch.try_set(ut.id, "FAILED"):
                                    self.emit(RuntimeEvent(EventKind.TASK_FAILED, ut.to_dict(), turn_id))

                        error_reason = self.last_verification.summary if not self.last_verification.passed else f"{len(remaining_unfinished)} task(s) remained unfinished."
                        run_id = self.current_run.run_id if self.current_run else turn_id
                        if self.terminal_latch.try_set(run_id, "FAILED"):
                            self.emit(RuntimeEvent(
                                EventKind.AGENT_FAILED,
                                {
                                    "goal": self.current_plan.goal,
                                    "plan": self.current_plan.to_dict(),
                                    "error": error_reason,
                                },
                                turn_id,
                            ))

                if self.current_run and self.current_run.target_deliverables:
                    all_exist, existing_files, _ = _verify_deliverables(
                        self.current_run.target_deliverables,
                        self.current_run.target_dir,
                        self.workspace,
                    )
                    if all_exist:
                        self.current_run.status = "completed"

                if self.current_plan and self.current_plan.state == AgentState.FAILED:
                    failed_titles = [task.title for task in self.current_plan.get_failed_tasks()]
                    details = []
                    if failed_titles:
                        details.append("blocked at: " + ", ".join(failed_titles[:3]))
                    if self.last_verification and not self.last_verification.passed:
                        details.append("verification: " + self.last_verification.summary)
                    detail = "; " + "; ".join(details) if details else ""
                    final = (
                        f"Task incomplete: {self.current_plan.completed_count}/{self.current_plan.total_count} "
                        f"plan steps completed{detail}."
                    )
                elif final_text:
                    final = final_text
                elif self.current_plan and self.current_plan.state == AgentState.COMPLETED:
                    final = "Task completed and verified, but no summary text was returned."
                else:
                    final = "No final response was produced; task completion is unconfirmed."
                history.append(ChatMessage(role="assistant", content=final))
                self.emit(RuntimeEvent(EventKind.TURN_COMPLETED, {"steps": step + 1, "final": final}, turn_id))
                plan_allows_speech = not self.current_plan or self.current_plan.state == AgentState.COMPLETED
                if directive.speech_text and plan_allows_speech and self.on_speech:
                    try:
                        self.on_speech(directive.speech_text)
                    except Exception as exc:
                        logger.debug("Marked speech delivery failed: %s", exc)
                profiler.finish()
                try:
                    from kratos_agent.memory import get_memory_manager
                    get_memory_manager().async_consolidate()
                except Exception as exc:
                    logger.debug("Async memory consolidation error: %s", exc)
                return final, history

            # Assistant Message with Tool Calls
            assistant_content = directive.display_text or ""
            if not assistant_content and response.tool_calls:
                call_strs = [f"call:{c.name}{json.dumps(c.arguments)}" for c in response.tool_calls]
                assistant_content = "\n".join(call_strs)

            history.append(ChatMessage(
                role="assistant",
                content=assistant_content,
                metadata={"tool_calls": [call.__dict__ for call in response.tool_calls]},
            ))

            # Execute Tool Calls in Parallel Waves
            waves = partition_tool_waves(response.tool_calls)
            for wave in waves:
                if self.cancellation_flag.is_set():
                    if self.current_plan:
                        self.current_plan.pause_running_tasks("Interrupted by user")
                        self.emit(RuntimeEvent(EventKind.AGENT_PAUSED, {"plan": self.current_plan.to_dict()}, turn_id))
                    message = "Agent execution was interrupted."
                    self.emit(RuntimeEvent(EventKind.TURN_FAILED, {"error": "cancelled", "plan": self.current_plan.to_dict() if self.current_plan else None}, turn_id))
                    profiler.finish()
                    return message, history

                # Determine if wave can execute concurrently
                use_parallel = (
                    len(wave) > 1
                    and is_parallel_execution_enabled()
                    and not self.cancellation_flag.is_set()
                )

                # Pre-execution: Register substeps and emit TOOL_CALL_STARTED for all calls in wave
                for call in wave:
                    active_task = None
                    if self.current_plan:
                        active_task = self.current_plan.get_active_task()
                        if not active_task:
                            pending = self.current_plan.get_pending_tasks()
                            if pending:
                                active_task = pending[0]
                                active_task.start()
                                self.emit(RuntimeEvent(EventKind.TASK_STARTED, active_task.to_dict(), turn_id))

                        if active_task:
                            sub_text = _format_tool_substep(call.name, call.arguments)
                            active_task.add_substep("⠋", sub_text, style="bold yellow", is_active=True)
                            file_path = str(call.arguments.get("file_path", "") or call.arguments.get("path", "") or call.arguments.get("target_file", ""))
                            self.current_plan.update_task_activity(active_task.id, file_path=file_path, increment_tool=True)
                            self.emit(RuntimeEvent(EventKind.TASK_UPDATED, active_task.to_dict(), turn_id))

                    action_label = format_tool_action_label(call.name, call.arguments)
                    display_label = f"[tool call] {action_label}"
                    self.emit(RuntimeEvent(
                        EventKind.TOOL_CALL_STARTED,
                        {
                            "name": call.name,
                            "arguments": call.arguments,
                            "call_id": call.call_id,
                            "action_label": action_label,
                            "display": display_label,
                        },
                        turn_id,
                    ))
                    if call.name == "run_terminal_command":
                        self.emit(RuntimeEvent(EventKind.COMMAND_STARTED, {"command": str(call.arguments.get("command", ""))}, turn_id))

                # Tool Execution: Parallel (concurrent worker pool) or Sequential
                with profiler.measure("tool"):
                    if use_parallel:
                        max_workers = min(len(wave), get_max_parallel_workers())
                        with ThreadPoolExecutor(max_workers=max_workers) as executor:
                            futures = [executor.submit(self._execute_tool_call_worker, c, allow_tool) for c in wave]
                            results = [f.result() for f in futures]
                    else:
                        results = [self._execute_tool_call_worker(c, allow_tool) for c in wave]

                # Post-execution: Process results in original wave order
                for call, result in zip(wave, results):
                    active_task = self.current_plan.get_active_task() if self.current_plan else None

                    kind = EventKind.TOOL_FAILED if result.is_error else EventKind.TOOL_COMPLETED
                    self.emit(RuntimeEvent(kind, result.__dict__, turn_id))

                    # Track side effects
                    self._track_tool_side_effects(call.name, call.arguments, result.is_error, turn_id)

                    # Update Active Task with Result and Concrete Evidence
                    if active_task:
                        if result.is_error:
                            active_task.resolve_substep("✗", f"Failed {call.name}: {result.content[:50]}", style="bold red")
                            active_task.state = TaskState.NEEDS_ATTENTION
                            active_task.detail = result.content[:120]
                            active_task.add_evidence(call.name, {"args": call.arguments, "is_error": True})
                            self.emit(RuntimeEvent(EventKind.TASK_FAILED, active_task.to_dict(), turn_id))
                        else:
                            res_sub = _format_tool_result_substep(call.name, call.arguments, result.content)
                            active_task.resolve_substep("✓", res_sub, style="dim green")
                            active_task.add_evidence(call.name, {"args": call.arguments, "is_error": False})

                            # File writing / editing tool completes file tasks
                            if call.name in ("write_file", "edit_file", "replace_file_content", "multi_replace_file_content"):
                                fp = call.arguments.get("file_path", "") or call.arguments.get("target_file", "")
                                allowed = True
                                if getattr(active_task, "requires_observable_evidence", False):
                                    allowed, _ = self._check_task_completion_gate(active_task, turn_id)
                                if allowed:
                                    active_task.complete(f"Updated {fp}", force=True)
                                    if self.terminal_latch.try_set(active_task.id, "COMPLETED"):
                                        self.emit(RuntimeEvent(EventKind.TASK_COMPLETED, active_task.to_dict(), turn_id))

                                    # Complete any pending earlier design/inspection tasks
                                    if self.current_plan:
                                        for prev_t in self.current_plan.tasks:
                                            if prev_t.id == active_task.id:
                                                break
                                            if prev_t.state in (TaskState.PENDING, TaskState.RUNNING):
                                                prev_t.complete("Completed prior to implementation", force=True)
                                                if self.terminal_latch.try_set(prev_t.id, "COMPLETED"):
                                                    self.emit(RuntimeEvent(EventKind.TASK_COMPLETED, prev_t.to_dict(), turn_id))

                                    # Start next pending task if available
                                    if self.current_plan:
                                        next_pending = self.current_plan.get_pending_tasks()
                                        if next_pending:
                                            next_t = next_pending[0]
                                            next_t.start()
                                            self.emit(RuntimeEvent(EventKind.TASK_STARTED, next_t.to_dict(), turn_id))

                            # Inspection/exploration read-only tools fulfill inspection-oriented tasks
                            elif call.name in READ_ONLY_TOOLS or call.name in ARTIFACT_INSPECTION_TOOLS:
                                task_title_lower = active_task.title.lower()
                                if any(kw in task_title_lower for kw in ("inspect", "analyze", "explore", "check", "diagnose", "search", "read", "review", "find")):
                                    allowed = True
                                    if getattr(active_task, "requires_observable_evidence", False):
                                        allowed, _ = self._check_task_completion_gate(active_task, turn_id)
                                    if allowed:
                                        active_task.complete(f"Inspected with {call.name}", force=True)
                                        if self.terminal_latch.try_set(active_task.id, "COMPLETED"):
                                            self.emit(RuntimeEvent(EventKind.TASK_COMPLETED, active_task.to_dict(), turn_id))
                                        if self.current_plan:
                                            next_pending = self.current_plan.get_pending_tasks()
                                            if next_pending:
                                                next_t = next_pending[0]
                                                next_t.start()
                                                self.emit(RuntimeEvent(EventKind.TASK_STARTED, next_t.to_dict(), turn_id))

                            # Command tools fulfill command-oriented tasks
                            elif call.name == "run_terminal_command":
                                cmd = str(call.arguments.get("command", "")).strip()
                                cmd_lower = cmd.lower()
                                task_title_lower = active_task.title.lower()

                                is_trivial_probe = any(cmd_lower.startswith(p) for p in ("cd", "dir", "ls", "pwd", "echo", "type ", "cat ", "where ", "which ", "if exist"))
                                is_scaffold_install = any(kw in cmd_lower for kw in ("npm ", "npx ", "pnpm ", "yarn ", "pip ", "uv ", "python ", "cargo ", "git clone", "create-vite", "vite"))
                                is_test_or_build = any(kw in cmd_lower for kw in ("test", "pytest", "npm run", "vite build", "build", "tsc", "cargo test", "check"))

                                should_complete = False
                                completion_msg = f"Ran {cmd[:35]}"

                                if any(kw in task_title_lower for kw in ("inspect", "analyze", "explore", "check", "diagnose", "search")):
                                    should_complete = True
                                    completion_msg = f"Inspected with {cmd[:30]}"
                                elif any(kw in task_title_lower for kw in ("scaffold", "install", "setup", "initialize", "dependency", "dependencies")):
                                    if is_scaffold_install or not is_trivial_probe:
                                        should_complete = True
                                        completion_msg = f"Setup via {cmd[:30]}"
                                elif any(kw in task_title_lower for kw in ("build", "test", "verify", "validation")):
                                    if is_test_or_build or not is_trivial_probe:
                                        should_complete = True
                                        completion_msg = f"Verified via {cmd[:30]}"
                                elif not is_trivial_probe:
                                    should_complete = True

                                if should_complete:
                                    allowed = True
                                    if getattr(active_task, "requires_observable_evidence", False):
                                        allowed, _ = self._check_task_completion_gate(active_task, turn_id)
                                    if allowed:
                                        active_task.complete(completion_msg, force=True)
                                        if self.terminal_latch.try_set(active_task.id, "COMPLETED"):
                                            self.emit(RuntimeEvent(EventKind.TASK_COMPLETED, active_task.to_dict(), turn_id))
                                        if self.current_plan:
                                            next_pending = self.current_plan.get_pending_tasks()
                                            if next_pending:
                                                next_t = next_pending[0]
                                                next_t.start()
                                                self.emit(RuntimeEvent(EventKind.TASK_STARTED, next_t.to_dict(), turn_id))
                                else:
                                    active_task.add_evidence("terminal_command", {"command": cmd[:80]})

                            self.emit(RuntimeEvent(EventKind.TASK_UPDATED, active_task.to_dict(), turn_id))

                    history.append(ChatMessage(
                        role="tool",
                        content=result.content,
                        name=result.name,
                        tool_call_id=result.call_id,
                        metadata={"is_error": result.is_error, "truncated": result.truncated},
                    ))

        message = (
            f"Stopped after {max_steps} agent steps to prevent an unbounded tool loop."
            if max_steps is not None
            else "Agent execution stopped before completion."
        )
        if self.current_plan:
            self.current_plan.pause_running_tasks("Step limit reached")
            self.current_plan.state = AgentState.FAILED
            self.emit(RuntimeEvent(EventKind.AGENT_FAILED, {"error": message, "plan": self.current_plan.to_dict()}, turn_id))
        self.emit(RuntimeEvent(EventKind.TURN_FAILED, {"error": message}, turn_id))
        return message, history


def _redacted_request(request: dict[str, Any]) -> dict[str, Any]:
    secret_keys = {"api_key", "authorization", "access_token", "refresh_token", "client_secret", "password"}
    clean = dict(request)
    for k in list(clean.keys()):
        if k in secret_keys:
            clean[k] = "[REDACTED]"
    return clean
