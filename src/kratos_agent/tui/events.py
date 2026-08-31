"""Event renderer: translates RuntimeEvents into live task tree displays and Rich renderables.

Renders:
- Goal header
- Live PLAN tree with task state glyphs (☐, ⠋, ✓, ✗, ⊘, ⚠) and nested tool activities (├─, └─)
- Progress indicator (e.g. Progress: 2/6)
- Status spinner
- StepRecord history for /debug trace
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from rich.console import RenderableType, Group
from rich.panel import Panel
from rich.rule import Rule
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from kratos_agent.core.task_manager import AgentState, ExecutionPlan, TaskItem, TaskState


def _elapsed(since: float) -> str:
    secs = time.monotonic() - since
    if secs < 1:
        return f"{secs*1000:.0f}ms"
    return f"{secs:.1f}s"


def _ms(duration_ms: int) -> str:
    if duration_ms < 1000:
        return f"{duration_ms}ms"
    return f"{duration_ms/1000:.1f}s"


@dataclass
class StepRecord:
    index: int
    kind: str
    label: str
    detail: str
    status: str
    started_at: float
    finished_at: Optional[float] = None
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    tool_output: Optional[str] = None
    output_truncated: bool = False
    error: Optional[str] = None
    usage: Optional[Dict[str, int]] = None

    @property
    def duration(self) -> Optional[str]:
        if self.finished_at:
            ms = int((self.finished_at - self.started_at) * 1000)
            return _ms(ms)
        return None


class EventRenderer:
    """Translates RuntimeEvents into live TUI structures."""

    def __init__(self, is_tty: bool = True) -> None:
        self.is_tty = is_tty
        self.steps: List[StepRecord] = []
        self.plan: Optional[ExecutionPlan] = None
        self.is_chat_mode: bool = False
        self.thinking_label: str = "Thinking…"
        self._turn_start: float = time.monotonic()
        self._step_idx: int = 0
        self._open_tool_steps: Dict[str, int] = {}
        self._thinking_step_idx: Optional[int] = None

    def reset(self) -> None:
        self.steps.clear()
        self.plan = None
        self.is_chat_mode = False
        self.thinking_label = "Thinking…"
        self._turn_start = time.monotonic()
        self._step_idx = 0
        self._open_tool_steps.clear()
        self._thinking_step_idx = None

    # ── Event Callbacks ────────────────────────────────────────────────────────

    def on_agent_started(self, payload: Dict[str, Any]) -> None:
        intent = payload.get("intent", "coding_task")
        self.is_chat_mode = (intent in ("chat", "question"))
        self.thinking_label = "Understanding request…"

    def on_understanding_started(self, payload: Dict[str, Any]) -> None:
        self.thinking_label = "Understanding request…"

    def on_planning_started(self, payload: Dict[str, Any]) -> None:
        self.thinking_label = "Formulating execution plan…"

    def on_plan_created(self, payload: Dict[str, Any]) -> None:
        self.plan = ExecutionPlan.from_dict(payload)
        self.thinking_label = f"Starting task 1/{self.plan.total_count}…"

    def on_plan_updated(self, payload: Dict[str, Any]) -> None:
        self.plan = ExecutionPlan.from_dict(payload)

    def on_task_started(self, payload: Dict[str, Any]) -> None:
        tid = payload.get("id", "")
        title = payload.get("title", "")
        if self.plan:
            self.plan.start_task(tid)
            idx = self.plan.get_active_index() + 1
            self.thinking_label = f"Task {idx}/{self.plan.total_count}: {title[:35]}…"
        else:
            self.thinking_label = f"Implementing: {title[:35]}…"

    def on_task_updated(self, payload: Dict[str, Any]) -> None:
        tid = payload.get("id", "")
        if self.plan:
            t = self.plan._find_task(tid)
            if t:
                state_val = payload.get("state")
                if state_val:
                    try:
                        t.state = TaskState(state_val)
                    except ValueError:
                        pass
                if payload.get("detail"):
                    t.detail = payload["detail"]

    def on_task_completed(self, payload: Dict[str, Any]) -> None:
        tid = payload.get("id", "")
        if self.plan:
            self.plan.complete_task(tid, payload.get("detail"))

    def on_task_failed(self, payload: Dict[str, Any]) -> None:
        tid = payload.get("id", "")
        if self.plan:
            self.plan.fail_task(tid, payload.get("detail", "Error"))

    def on_thinking_started(self) -> None:
        idx = self._step_idx
        self._step_idx += 1
        step = StepRecord(
            index=idx,
            kind="thinking",
            label="Thinking",
            detail=self.thinking_label,
            status="thinking",
            started_at=time.monotonic(),
        )
        self.steps.append(step)
        self._thinking_step_idx = idx

    def on_model_response(self, payload: Dict[str, Any]) -> None:
        if self._thinking_step_idx is not None:
            step = self.steps[self._thinking_step_idx]
            step.status = "success"
            step.finished_at = time.monotonic()
            step.usage = payload.get("usage") or {}
            self._thinking_step_idx = None

    def on_tool_requested(self, payload: Dict[str, Any]) -> None:
        name = payload.get("name", "tool")
        args = payload.get("arguments", {})
        call_id = payload.get("call_id", "")
        idx = self._step_idx
        self._step_idx += 1

        detail = ""
        if "file_path" in args:
            detail = str(args["file_path"])
        elif "command" in args:
            detail = str(args["command"])[:70]

        step = StepRecord(
            index=idx,
            kind="tool",
            label=name,
            detail=detail,
            status="running",
            started_at=time.monotonic(),
            tool_name=name,
            tool_args=args,
        )
        self.steps.append(step)
        self._open_tool_steps[call_id] = idx

        if name == "write_file":
            self.thinking_label = f"Writing {args.get('file_path', '')}…"
        elif name == "edit_file":
            self.thinking_label = f"Editing {args.get('file_path', '')}…"
        elif name == "run_terminal_command":
            self.thinking_label = f"Running command…"

    def on_tool_completed(self, payload: Dict[str, Any], failed: bool = False) -> None:
        call_id = payload.get("call_id", "")
        content = payload.get("content", "")
        is_error = payload.get("is_error", False) or failed

        idx = self._open_tool_steps.pop(call_id, None)
        if idx is not None and idx < len(self.steps):
            step = self.steps[idx]
            step.status = "failed" if is_error else "success"
            step.finished_at = time.monotonic()
            step.tool_output = content[:400]
            if is_error:
                step.error = content[:150]

    def on_verification_started(self, payload: Dict[str, Any]) -> None:
        self.thinking_label = "Verifying application & changed files…"

    def on_verification_completed(self, payload: Dict[str, Any]) -> None:
        passed = payload.get("passed", True)
        self.thinking_label = "Verification complete." if passed else "Verification encountered issues."

    # ── Live Plan Tree Rendering ───────────────────────────────────────────────

    def render_plan_tree(self) -> Optional[RenderableType]:
        """Renders the clean structured PLAN tree with nested tool substeps."""
        if not self.plan or not self.plan.tasks or self.is_chat_mode:
            return None

        lines: List[RenderableType] = []

        # Goal Header
        if self.plan.goal:
            goal_text = Text()
            goal_text.append("Goal\n", style="bold #D4AF37")
            goal_text.append(f"{self.plan.goal}\n", style="bold white")
            lines.append(goal_text)

        # PLAN Header
        plan_header = Text()
        plan_header.append("PLAN\n", style="bold gold1")
        lines.append(plan_header)

        # Task Items & Substeps
        for idx, task in enumerate(self.plan.tasks, 1):
            t_line = Text()
            if task.state == TaskState.COMPLETED:
                t_line.append("  ✓ ", style="bold green")
                t_line.append(f"{idx}. {task.title}", style="bold green")
            elif task.state == TaskState.RUNNING:
                t_line.append("  ⠋ ", style="bold yellow")
                t_line.append(f"{idx}. {task.title}", style="bold yellow")
            elif task.state == TaskState.FAILED:
                t_line.append("  ✗ ", style="bold red")
                t_line.append(f"{idx}. {task.title}", style="bold red")
            elif task.state == TaskState.NEEDS_ATTENTION:
                t_line.append("  ⚠ ", style="bold yellow")
                t_line.append(f"{idx}. {task.title}", style="bold yellow")
            elif task.state == TaskState.SKIPPED:
                t_line.append("  ⊘ ", style="dim")
                t_line.append(f"{idx}. {task.title}", style="dim")
            else:
                t_line.append("  ☐ ", style="dim white")
                t_line.append(f"{idx}. {task.title}", style="dim white")

            lines.append(t_line)

            # Substeps / Tool activities nested under this task
            if task.substeps:
                total_subs = len(task.substeps)
                for s_idx, sub in enumerate(task.substeps[-5:], 1):
                    is_last = (s_idx == min(total_subs, 5))
                    branch = "└─" if is_last else "├─"
                    s_line = Text()
                    s_line.append(f"    {branch} ", style="dim #555")
                    if sub.is_active:
                        s_line.append("⠋ ", style="bold yellow")
                        s_line.append(sub.text, style="yellow")
                    elif sub.glyph == "✓":
                        s_line.append("✓ ", style="green")
                        s_line.append(sub.text, style="dim white")
                    elif sub.glyph == "✗":
                        s_line.append("✗ ", style="bold red")
                        s_line.append(sub.text, style="dim red")
                    else:
                        s_line.append(f"{sub.glyph} ", style="dim")
                        s_line.append(sub.text, style="dim white")
                    lines.append(s_line)

            # Error details
            if task.detail and task.state in (TaskState.FAILED, TaskState.NEEDS_ATTENTION):
                e_line = Text()
                e_line.append(f"    └─ [Error: {task.detail[:60]}]", style="dim red")
                lines.append(e_line)

        # Progress summary
        progress_text = Text()
        progress_text.append(f"\nProgress: {self.plan.progress_summary}", style="bold cyan")
        lines.append(progress_text)

        return Group(*lines)

    def render_thinking_line(self) -> RenderableType:
        t = Text()
        t.append(f" {self.thinking_label}", style="bold cyan")
        elapsed = _elapsed(self._turn_start)
        t.append(f"  [{elapsed}]", style="dim yellow")
        spinner = Spinner("dots", text=t)
        spinner.start_time = self._turn_start
        return spinner

    def total_elapsed(self) -> str:
        return _elapsed(self._turn_start)
