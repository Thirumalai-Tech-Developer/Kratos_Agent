"""Structured task management, agent state machine, and live execution plan state for Kratos Agent.

Tracks discrete agent states (IDLE, ANALYZING, PLANNING, EXECUTING, VERIFYING, COMPLETED,
FAILED, INTERRUPTED) along with dynamic task lists, nested tool activities, evidence tracking, and progress.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union


class AgentState(str, Enum):
    IDLE = "idle"
    ANALYZING = "analyzing"
    PLANNING = "planning"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"

    @property
    def badge(self) -> str:
        return {
            AgentState.IDLE: "[dim]IDLE[/dim]",
            AgentState.ANALYZING: "[bold cyan]ANALYZING[/bold cyan]",
            AgentState.PLANNING: "[bold gold1]PLANNING[/bold gold1]",
            AgentState.EXECUTING: "[bold green]EXECUTING[/bold green]",
            AgentState.VERIFYING: "[bold magenta]VERIFYING[/bold magenta]",
            AgentState.COMPLETED: "[bold green]COMPLETED[/bold green]",
            AgentState.FAILED: "[bold red]FAILED[/bold red]",
            AgentState.INTERRUPTED: "[bold yellow]INTERRUPTED[/bold yellow]",
        }[self]


class TaskState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    NEEDS_ATTENTION = "needs_attention"

    @property
    def glyph(self) -> str:
        return {
            TaskState.PENDING: "☐",
            TaskState.RUNNING: "⠋",
            TaskState.COMPLETED: "✓",
            TaskState.FAILED: "✗",
            TaskState.SKIPPED: "⊘",
            TaskState.NEEDS_ATTENTION: "⚠",
        }[self]

    @property
    def style(self) -> str:
        return {
            TaskState.PENDING: "dim white",
            TaskState.RUNNING: "bold yellow",
            TaskState.COMPLETED: "bold green",
            TaskState.FAILED: "bold red",
            TaskState.SKIPPED: "dim",
            TaskState.NEEDS_ATTENTION: "bold yellow",
        }[self]


@dataclass
class SubStep:
    id: str
    glyph: str
    text: str
    style: str = "dim white"
    is_active: bool = False
    started_at: float = field(default_factory=time.monotonic)
    finished_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "glyph": self.glyph,
            "text": self.text,
            "style": self.style,
            "is_active": self.is_active,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SubStep:
        return cls(
            id=data.get("id", str(uuid.uuid4())[:6]),
            glyph=data.get("glyph", "✓"),
            text=data.get("text", ""),
            style=data.get("style", "dim white"),
            is_active=data.get("is_active", False),
            started_at=data.get("started_at", time.monotonic()),
            finished_at=data.get("finished_at"),
        )


@dataclass
class TaskItem:
    id: str
    title: str
    state: TaskState = TaskState.PENDING
    detail: Optional[str] = None
    verification: str = "none"  # "none", "build", "tests", "browser", "browser+build"
    substeps: List[SubStep] = field(default_factory=list)
    files_affected: List[str] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    tool_count: int = 0
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    def start(self) -> None:
        self.state = TaskState.RUNNING
        self.started_at = time.monotonic()

    def add_evidence(self, kind: str, data: Optional[Dict[str, Any]] = None) -> None:
        """Records concrete tool execution or verification evidence for this task."""
        entry = {"kind": kind, "timestamp": time.monotonic(), "data": data or {}}
        self.evidence.append(entry)

    def has_evidence(self) -> bool:
        """Returns True only if actual tool execution or verified side-effects exist."""
        return (
            len(self.evidence) > 0
            or self.tool_count > 0
            or len(self.files_affected) > 0
            or any(s.glyph == "✓" for s in self.substeps)
        )

    def complete(self, detail: Optional[str] = None, force: bool = True) -> bool:
        self.state = TaskState.COMPLETED
        self.finished_at = time.monotonic()
        # Mark all active substeps completed
        for sub in self.substeps:
            if sub.is_active:
                sub.is_active = False
                sub.glyph = "✓"
                sub.style = "dim green"
                sub.finished_at = time.monotonic()
        if detail:
            self.detail = detail
        return True

    def fail(self, error: Optional[str] = None) -> None:
        self.state = TaskState.FAILED
        self.finished_at = time.monotonic()
        for sub in self.substeps:
            if sub.is_active:
                sub.is_active = False
                sub.glyph = "✗"
                sub.style = "dim red"
                sub.finished_at = time.monotonic()
        if error:
            self.detail = error

    def skip(self, reason: Optional[str] = None) -> None:
        self.state = TaskState.SKIPPED
        self.finished_at = time.monotonic()
        if reason:
            self.detail = reason

    def add_substep(self, glyph: str, text: str, style: str = "dim white", is_active: bool = False) -> SubStep:
        # Check if already exists with same text to avoid duplicates
        for existing in self.substeps:
            if existing.text == text and not is_active:
                existing.glyph = glyph
                existing.style = style
                existing.is_active = False
                return existing
        sub = SubStep(id=str(uuid.uuid4())[:6], glyph=glyph, text=text, style=style, is_active=is_active)
        self.substeps.append(sub)
        return sub

    def resolve_substep(self, glyph: str, text: str, style: str = "dim green") -> None:
        for sub in reversed(self.substeps):
            if sub.is_active:
                sub.glyph = glyph
                sub.text = text
                sub.style = style
                sub.is_active = False
                sub.finished_at = time.monotonic()
                return
        self.add_substep(glyph, text, style=style, is_active=False)

    def add_file(self, file_path: str) -> None:
        if file_path and file_path not in self.files_affected:
            self.files_affected.append(file_path)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "state": self.state.value,
            "detail": self.detail,
            "verification": self.verification,
            "substeps": [s.to_dict() for s in self.substeps],
            "files_affected": list(self.files_affected),
            "evidence": list(self.evidence),
            "tool_count": self.tool_count,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TaskItem:
        state_val = data.get("state", "pending")
        try:
            state = TaskState(state_val)
        except ValueError:
            state = TaskState.PENDING
        substeps = [SubStep.from_dict(s) for s in data.get("substeps", [])]
        return cls(
            id=str(data.get("id", str(uuid.uuid4())[:6])),
            title=str(data.get("title", "Untitled Task")),
            state=state,
            detail=data.get("detail"),
            verification=str(data.get("verification", "none")),
            substeps=substeps,
            files_affected=list(data.get("files_affected", [])),
            evidence=list(data.get("evidence", [])),
            tool_count=int(data.get("tool_count", 0)),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
        )


class ExecutionPlan:
    """Manages an active execution plan, supporting live task trees, goal tracking, evidence, and serialization."""

    def __init__(
        self,
        goal: str = "",
        tasks: Optional[List[TaskItem]] = None,
        title: str = "PLAN",
    ) -> None:
        self.goal = goal
        self.title = title
        self.tasks: List[TaskItem] = tasks or []
        self.state: AgentState = AgentState.IDLE
        self.created_at: float = time.time()
        self.updated_at: float = self.created_at

    def set_tasks_from_titles(self, titles: List[str], goal: str = "") -> None:
        if goal:
            self.goal = goal
        self.tasks = [
            TaskItem(id=str(idx + 1), title=t.strip(), state=TaskState.PENDING)
            for idx, t in enumerate(titles)
            if t.strip()
        ]
        self.updated_at = time.time()

    def add_task(self, title: str, state: TaskState = TaskState.PENDING, task_id: Optional[str] = None) -> TaskItem:
        tid = task_id or str(len(self.tasks) + 1)
        item = TaskItem(id=tid, title=title.strip(), state=state)
        self.tasks.append(item)
        self.updated_at = time.time()
        return item

    def insert_task(self, index: int, title: str, state: TaskState = TaskState.PENDING) -> TaskItem:
        tid = str(len(self.tasks) + 1)
        item = TaskItem(id=tid, title=title.strip(), state=state)
        insert_idx = max(0, min(index, len(self.tasks)))
        self.tasks.insert(insert_idx, item)
        self.updated_at = time.time()
        return item

    def _find_task(self, key: Union[int, str]) -> Optional[TaskItem]:
        if isinstance(key, int):
            if 0 <= key < len(self.tasks):
                return self.tasks[key]
            return None
        key_str = str(key).strip().lower()
        for t in self.tasks:
            tid_str = str(t.id).lower()
            if (
                tid_str == key_str
                or f"task_{tid_str}" == key_str
                or f"task-{tid_str}" == key_str
                or f"task {tid_str}" == key_str
                or t.title.lower() == key_str
            ):
                return t
        return None

    def start_task(self, key: Union[int, str]) -> Optional[TaskItem]:
        task = self._find_task(key)
        if task:
            task.start()
            self.updated_at = time.time()
        return task

    def complete_task(self, key: Union[int, str], detail: Optional[str] = None, force: bool = False) -> Optional[TaskItem]:
        task = self._find_task(key)
        if task:
            task.complete(detail, force=force)
            self.updated_at = time.time()
        return task

    def fail_task(self, key: Union[int, str], error: Optional[str] = None) -> Optional[TaskItem]:
        task = self._find_task(key)
        if task:
            task.fail(error)
            self.updated_at = time.time()
        return task

    def skip_task(self, key: Union[int, str], reason: Optional[str] = None) -> Optional[TaskItem]:
        task = self._find_task(key)
        if task:
            task.skip(reason)
            self.updated_at = time.time()
        return task

    def add_substep(self, key: Union[int, str], glyph: str, text: str, style: str = "dim white", is_active: bool = False) -> Optional[SubStep]:
        task = self._find_task(key)
        if not task:
            task = self.get_active_task()
        if task:
            sub = task.add_substep(glyph, text, style=style, is_active=is_active)
            self.updated_at = time.time()
            return sub
        return None

    def resolve_substep(self, key: Union[int, str], glyph: str, text: str, style: str = "dim green") -> None:
        task = self._find_task(key)
        if not task:
            task = self.get_active_task()
        if task:
            task.resolve_substep(glyph, text, style=style)
            self.updated_at = time.time()

    def update_task_activity(self, key: Union[int, str], file_path: Optional[str] = None, increment_tool: bool = True) -> None:
        task = self._find_task(key)
        if task:
            if file_path:
                task.add_file(file_path)
            if increment_tool:
                task.tool_count += 1
            self.updated_at = time.time()

    def get_active_task(self) -> Optional[TaskItem]:
        for t in self.tasks:
            if t.state == TaskState.RUNNING:
                return t
        return None

    def get_active_index(self) -> int:
        for i, t in enumerate(self.tasks):
            if t.state in (TaskState.RUNNING, TaskState.PENDING):
                return i
        return max(0, len(self.tasks) - 1)

    def get_pending_tasks(self) -> List[TaskItem]:
        return [t for t in self.tasks if t.state == TaskState.PENDING]

    def get_completed_tasks(self) -> List[TaskItem]:
        return [t for t in self.tasks if t.state == TaskState.COMPLETED]

    def get_failed_tasks(self) -> List[TaskItem]:
        return [t for t in self.tasks if t.state in (TaskState.FAILED, TaskState.NEEDS_ATTENTION)]

    def get_unfinished_tasks(self) -> List[TaskItem]:
        return [t for t in self.tasks if t.state not in (TaskState.COMPLETED, TaskState.SKIPPED)]

    @property
    def total_count(self) -> int:
        return len(self.tasks)

    @property
    def completed_count(self) -> int:
        return len([t for t in self.tasks if t.state == TaskState.COMPLETED])

    @property
    def progress_percent(self) -> int:
        if not self.tasks:
            return 0
        return int((self.completed_count / len(self.tasks)) * 100)

    @property
    def progress_summary(self) -> str:
        return f"{self.completed_count}/{self.total_count}"

    @property
    def is_all_completed(self) -> bool:
        if not self.tasks:
            return False
        return all(t.state in (TaskState.COMPLETED, TaskState.SKIPPED) for t in self.tasks)

    def pause_running_tasks(self, reason: str = "Interrupted") -> None:
        for t in self.tasks:
            if t.state == TaskState.RUNNING:
                t.state = TaskState.NEEDS_ATTENTION
                t.detail = reason
        self.state = AgentState.INTERRUPTED
        self.updated_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "title": self.title,
            "state": self.state.value,
            "tasks": [t.to_dict() for t in self.tasks],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "total_count": self.total_count,
            "completed_count": self.completed_count,
            "progress_percent": self.progress_percent,
            "progress_summary": self.progress_summary,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ExecutionPlan:
        tasks = [TaskItem.from_dict(t) for t in data.get("tasks", [])]
        plan = cls(goal=data.get("goal", ""), tasks=tasks, title=data.get("title", "PLAN"))
        state_val = data.get("state", "idle")
        try:
            plan.state = AgentState(state_val)
        except ValueError:
            plan.state = AgentState.IDLE
        plan.created_at = data.get("created_at", time.time())
        plan.updated_at = data.get("updated_at", plan.created_at)
        return plan
