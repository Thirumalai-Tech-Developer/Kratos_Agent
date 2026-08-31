"""Autonomous agent loop for Kratos with intent classification, structured planning,
live task tree progression, workspace tracking, verification, and resilient interrupt/resume.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .context_pipeline import ContextBuilder
from .event_bus import event_bus
from .planner import IntentKind, classify_intent, formulate_agent_plan
from .runtime_contracts import ChatMessage, EventKind, RuntimeEvent
from .task_manager import AgentState, ExecutionPlan, TaskItem, TaskState
from .verification_manager import VerificationManager, VerificationResult
from .workspace_tracker import WorkspaceTracker


def _format_tool_substep(name: str, args: Dict[str, Any]) -> str:
    if name == "write_file":
        fp = str(args.get("file_path", ""))
        return f"Creating {fp}"
    if name == "edit_file":
        fp = str(args.get("file_path", ""))
        return f"Updating {fp}"
    if name == "read_file":
        fp = str(args.get("file_path", ""))
        return f"Inspecting {fp}"
    if name == "list_directory":
        path = str(args.get("directory_path", "") or args.get("path", "."))
        return f"Inspecting {path}/"
    if name == "grep_search":
        q = str(args.get("query", ""))
        return f"Searching for '{q[:30]}'"
    if name == "run_terminal_command":
        cmd = str(args.get("command", ""))
        return f"Running {cmd[:45]}"
    return f"Executing {name}"


def _format_tool_result_substep(name: str, args: Dict[str, Any], content: str) -> str:
    if name == "write_file":
        fp = str(args.get("file_path", ""))
        return f"Created {fp}"
    if name == "edit_file":
        fp = str(args.get("file_path", ""))
        return f"Updated {fp}"
    if name == "read_file":
        fp = str(args.get("file_path", ""))
        return f"Inspected {fp}"
    if name == "list_directory":
        return "Inspected directory structure"
    if name == "grep_search":
        return "Search completed"
    if name == "run_terminal_command":
        cmd = str(args.get("command", ""))
        return f"Ran {cmd[:45]}"
    return f"Completed {name}"


class AgentLoop:
    def __init__(
        self,
        context: ContextBuilder,
        instructions: Any,
        tools: Any,
        model: Any,
        emit: Callable[[RuntimeEvent], None],
        workspace: Path,
        cancellation_flag: Optional[threading.Event] = None,
    ) -> None:
        self.context = context
        self.instructions = instructions
        self.tools = tools
        self.model = model
        self.emit_fn = emit
        self.workspace = workspace.resolve()
        self.cancellation_flag: threading.Event = cancellation_flag or threading.Event()

        self.workspace_tracker = WorkspaceTracker(self.workspace)
        self.verification_manager = VerificationManager(self.workspace, self.emit)
        self.current_plan: Optional[ExecutionPlan] = None
        self.last_verification: Optional[VerificationResult] = None

    def emit(self, event: RuntimeEvent) -> None:
        """Emits event through both the direct callback and the global EventBus."""
        try:
            self.emit_fn(event)
        except Exception:
            pass
        try:
            event_bus.publish(event)
        except Exception:
            pass

    def cancel(self) -> None:
        """Signal this loop to cancel at the next tool boundary."""
        self.cancellation_flag.set()

    def clear_cancel(self) -> None:
        """Clear any pending cancellation signal."""
        self.cancellation_flag.clear()

    def _track_tool_side_effects(self, name: str, args: Dict[str, Any], is_error: bool, turn_id: str) -> None:
        fp = str(args.get("file_path", "") or args.get("path", "")).strip()

        if name == "write_file":
            if not is_error and fp:
                self.workspace_tracker.record_file_created(fp)
                self.emit(RuntimeEvent(EventKind.FILE_CREATED, {"file_path": fp}, turn_id))
        elif name == "edit_file":
            if not is_error and fp:
                self.workspace_tracker.record_file_modified(fp)
                self.emit(RuntimeEvent(EventKind.FILE_MODIFIED, {"file_path": fp}, turn_id))
        elif name in ("read_file", "list_directory", "grep_search"):
            if fp:
                self.workspace_tracker.record_file_inspected(fp)
                self.emit(RuntimeEvent(EventKind.FILE_INSPECTED, {"file_path": fp}, turn_id))
        elif name == "run_terminal_command":
            cmd = str(args.get("command", "")).strip()
            if cmd:
                self.workspace_tracker.record_command(cmd, 1 if is_error else 0)
                self.emit(RuntimeEvent(EventKind.COMMAND_COMPLETED, {"command": cmd, "is_error": is_error}, turn_id))

    def run(
        self,
        history: List[ChatMessage],
        allow_tool: Callable[..., tuple[bool, str]],
        max_steps: int = 24,
        resume_plan: Optional[ExecutionPlan] = None,
    ) -> tuple[str, List[ChatMessage]]:
        turn_id = uuid.uuid4().hex
        self.workspace_tracker.reset()
        self.last_verification = None

        # 1. Identify User Prompt & Intent
        user_query = ""
        for m in reversed(history):
            if m.role == "user":
                user_query = m.content
                break

        is_continue = user_query.strip().lower() in ("continue", "resume", "/continue")
        intent = IntentKind.CODING_TASK if is_continue else classify_intent(user_query, history)

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
        for step in range(max_steps):
            # Check cancellation flag
            if self.cancellation_flag.is_set():
                if self.current_plan:
                    self.current_plan.pause_running_tasks("Interrupted by user")
                    self.emit(RuntimeEvent(EventKind.AGENT_PAUSED, {"plan": self.current_plan.to_dict()}, turn_id))
                message = "Agent execution was interrupted."
                self.emit(RuntimeEvent(EventKind.TURN_FAILED, {"error": "cancelled", "plan": self.current_plan.to_dict() if self.current_plan else None}, turn_id))
                return message, history

            # Assemble Context & Request
            built = self.context.assemble(
                self.instructions.build(),
                history,
                self.tools.schemas(),
                {"cwd": str(self.workspace), "platform": "windows"},
            )
            if built["compaction"]:
                self.emit(RuntimeEvent(EventKind.COMPACTED, built["compaction"], turn_id))
            request = built["request"]
            self.emit(RuntimeEvent(EventKind.REQUEST_ASSEMBLED, _redacted_request(request), turn_id))

            # Complete Model Request
            try:
                response = self.model.complete(request)
            except Exception as exc:
                if self.current_plan:
                    active = self.current_plan.get_active_task()
                    if active:
                        active.fail(str(exc))
                self.emit(RuntimeEvent(EventKind.TURN_FAILED, {"error": f"{type(exc).__name__}: {exc}"}, turn_id))
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
            if not response.tool_calls:
                final_text = response.text.strip()

                # If we have an active plan with unfinished tasks, check if tools are needed or verification applies
                if self.current_plan and self.current_plan.tasks:
                    active = self.current_plan.get_active_task()
                    unfinished = self.current_plan.get_unfinished_tasks()

                    # If model just stated intent without calling any tools on an active task
                    if active and not active.has_evidence() and len(self.workspace_tracker.all_changed_files) == 0 and conversational_nudge_count < 2:
                        history.append(ChatMessage(role="assistant", content=final_text or "Inspecting..."))
                        history.append(ChatMessage(
                            role="user",
                            content=(
                                f"[System Directive]: You stated intent ('{final_text}') for active task '{active.title}', but did not output a tool call. "
                                "You MUST execute the action now using the tool calling syntax. "
                                "Output: `call:write_file{\"file_path\": \"...\", \"content\": \"...\"}` or `call:run_terminal_command{\"command\": \"...\"}` or `call:list_directory{\"path\": \".\"}`. "
                                "Do NOT respond with conversational text without a tool call."
                            )
                        ))
                        conversational_nudge_count += 1
                        continue

                    # 4. Dedicated Verification Phase
                    self.current_plan.state = AgentState.VERIFYING
                    changed = self.workspace_tracker.all_changed_files
                    verif_types = [t.verification for t in self.current_plan.tasks if getattr(t, "verification", "none") != "none"]
                    verif_type = "+".join(sorted(set(verif_types))) if verif_types else "auto"
                    require_files = any(len(t.files_affected) > 0 for t in self.current_plan.tasks) or len(self.workspace_tracker.created_files) > 0 or any("file" in t.title.lower() or "scaffold" in t.title.lower() or "html" in t.title.lower() or "app" in t.title.lower() for t in self.current_plan.tasks)
                    browser_done = any("browser" in e.get("kind", "").lower() for t in self.current_plan.tasks for e in t.evidence)
                    self.last_verification = self.verification_manager.verify_workspace(
                        changed,
                        verification_type=verif_type,
                        require_files=require_files,
                        browser_performed=browser_done,
                        turn_id=turn_id,
                    )

                    # If verification passed and files were validated, fulfill all verified tasks with evidence
                    if self.last_verification and self.last_verification.passed and self.last_verification.files_checked > 0:
                        for t in self.current_plan.tasks:
                            if t.state in (TaskState.PENDING, TaskState.RUNNING):
                                t.add_evidence("verification", {"files_checked": self.last_verification.files_checked})
                                t.complete(f"Verified {self.last_verification.files_checked} file(s)")
                                self.emit(RuntimeEvent(EventKind.TASK_COMPLETED, t.to_dict(), turn_id))
                    elif self.last_verification.passed and not require_files:
                        for t in self.current_plan.tasks:
                            if t.has_evidence() and t.state != TaskState.COMPLETED:
                                t.complete("Completed")
                                self.emit(RuntimeEvent(EventKind.TASK_COMPLETED, t.to_dict(), turn_id))

                    # Check unfinished tasks
                    remaining_unfinished = self.current_plan.get_unfinished_tasks()

                    # Only complete overall plan if all tasks are COMPLETED and verification passed
                    all_done = (len(remaining_unfinished) == 0 and len(self.current_plan.tasks) > 0)
                    if self.last_verification.passed and all_done:
                        self.current_plan.state = AgentState.COMPLETED
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
                                self.emit(RuntimeEvent(EventKind.TASK_FAILED, ut.to_dict(), turn_id))

                        error_reason = self.last_verification.summary if not self.last_verification.passed else f"{len(remaining_unfinished)} task(s) remained unfinished."
                        self.emit(RuntimeEvent(
                            EventKind.AGENT_FAILED,
                            {
                                "goal": self.current_plan.goal,
                                "plan": self.current_plan.to_dict(),
                                "error": error_reason,
                            },
                            turn_id,
                        ))

                final = final_text or "Task execution finished."
                history.append(ChatMessage(role="assistant", content=final))
                self.emit(RuntimeEvent(EventKind.TURN_COMPLETED, {"steps": step + 1, "final": final}, turn_id))
                return final, history

            # Assistant Message with Tool Calls
            conversational_nudge_count = 0
            assistant_content = response.text or ""
            if not assistant_content and response.tool_calls:
                call_strs = [f"call:{c.name}{json.dumps(c.arguments)}" for c in response.tool_calls]
                assistant_content = "\n".join(call_strs)

            history.append(ChatMessage(
                role="assistant",
                content=assistant_content,
                metadata={"tool_calls": [call.__dict__ for call in response.tool_calls]},
            ))

            # Execute Each Tool Call
            for call in response.tool_calls:
                if self.cancellation_flag.is_set():
                    if self.current_plan:
                        self.current_plan.pause_running_tasks("Interrupted by user")
                        self.emit(RuntimeEvent(EventKind.AGENT_PAUSED, {"plan": self.current_plan.to_dict()}, turn_id))
                    message = "Agent execution was interrupted."
                    self.emit(RuntimeEvent(EventKind.TURN_FAILED, {"error": "cancelled", "plan": self.current_plan.to_dict() if self.current_plan else None}, turn_id))
                    return message, history

                # Find or start active task in plan
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
                        file_path = str(call.arguments.get("file_path", "") or call.arguments.get("path", ""))
                        self.current_plan.update_task_activity(active_task.id, file_path=file_path, increment_tool=True)
                        self.emit(RuntimeEvent(EventKind.TASK_UPDATED, active_task.to_dict(), turn_id))

                self.emit(RuntimeEvent(
                    EventKind.TOOL_CALL_STARTED,
                    {"name": call.name, "arguments": call.arguments, "call_id": call.call_id},
                    turn_id,
                ))
                if call.name == "run_terminal_command":
                    self.emit(RuntimeEvent(EventKind.COMMAND_STARTED, {"command": str(call.arguments.get("command", ""))}, turn_id))

                # Execute Tool
                result = self.tools.execute(call, allow_tool)
                output, truncated = self.context.prune_tool_result(result.content)
                result.content, result.truncated = output, truncated

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
                        if call.name in ("write_file", "edit_file"):
                            fp = call.arguments.get("file_path", "")
                            active_task.complete(f"Updated {fp}", force=True)
                            self.emit(RuntimeEvent(EventKind.TASK_COMPLETED, active_task.to_dict(), turn_id))

                            # Start next pending task if available
                            if self.current_plan:
                                next_pending = self.current_plan.get_pending_tasks()
                                if next_pending:
                                    next_t = next_pending[0]
                                    next_t.start()
                                    self.emit(RuntimeEvent(EventKind.TASK_STARTED, next_t.to_dict(), turn_id))

                        # Command tools fulfill command-oriented tasks
                        elif call.name == "run_terminal_command":
                            cmd = str(call.arguments.get("command", ""))
                            # If task indicates building, running, testing, or installing, complete it
                            if any(kw in active_task.title.lower() for kw in ("run", "install", "build", "test", "start", "verify", "scaffold", "setup", "check")):
                                active_task.complete(f"Ran {cmd[:35]}", force=True)
                                self.emit(RuntimeEvent(EventKind.TASK_COMPLETED, active_task.to_dict(), turn_id))
                                if self.current_plan:
                                    next_pending = self.current_plan.get_pending_tasks()
                                    if next_pending:
                                        next_t = next_pending[0]
                                        next_t.start()
                                        self.emit(RuntimeEvent(EventKind.TASK_STARTED, next_t.to_dict(), turn_id))

                        self.emit(RuntimeEvent(EventKind.TASK_UPDATED, active_task.to_dict(), turn_id))

                history.append(ChatMessage(
                    role="tool",
                    content=result.content,
                    name=result.name,
                    tool_call_id=result.call_id,
                    metadata={"is_error": result.is_error, "truncated": result.truncated},
                ))

        message = f"Stopped after {max_steps} agent steps to prevent an unbounded tool loop."
        if self.current_plan:
            self.current_plan.pause_running_tasks("Step limit reached")
            self.current_plan.state = AgentState.FAILED
            self.emit(RuntimeEvent(EventKind.AGENT_FAILED, {"error": message, "plan": self.current_plan.to_dict()}, turn_id))
        self.emit(RuntimeEvent(EventKind.TURN_FAILED, {"error": message}, turn_id))
        return message, history


def _redacted_request(request: Dict[str, Any]) -> Dict[str, Any]:
    secret_keys = {"api_key", "authorization", "access_token", "refresh_token", "client_secret", "password"}
    clean = dict(request)
    for k in list(clean.keys()):
        if k in secret_keys:
            clean[k] = "[REDACTED]"
    return clean
