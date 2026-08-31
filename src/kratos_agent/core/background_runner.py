"""
Background Async Agent Loop for Kratos Agent.
Implements Kimi Code "Agent Swarm" + Claude Code background task concepts.

Usage (CLI commands added to cli.py):
  /bg-run <prompt>   — Launch a prompt in a background daemon thread
  /bg-status         — List all background tasks with status
  /bg-result <id>    — Show the result of a completed background task
  /bg-cancel <id>    — Attempt to cancel a running task (marks it cancelled)
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional

from rich.console import Console
from rich.table import Table

console = Console(highlight=False)


class TaskStatus(str, Enum):
    PENDING  = "pending"
    RUNNING  = "running"
    DONE     = "done"
    ERROR    = "error"
    CANCELLED = "cancelled"


@dataclass
class BackgroundTask:
    id: str
    prompt: str
    status: TaskStatus = TaskStatus.PENDING
    result: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    _cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def short_id(self) -> str:
        return self.id[:8]

    @property
    def elapsed(self) -> str:
        if self.finished_at and self.started_at:
            return f"{self.finished_at - self.started_at:.1f}s"
        if self.started_at:
            return f"{time.time() - self.started_at:.1f}s"
        return "—"


class BackgroundRunner:
    """
    Manages background agent tasks in daemon threads.
    Tasks run independently of the main conversation loop.
    """

    def __init__(self):
        self._tasks: Dict[str, BackgroundTask] = {}
        self._lock = threading.Lock()

    def run(self, prompt: str, agent_fn: Callable[[str], str]) -> BackgroundTask:
        """
        Launch a prompt in the background. 
        agent_fn is the callable that invokes the Kratos runtime.
        Returns the BackgroundTask immediately.
        """
        task_id = str(uuid.uuid4())
        task = BackgroundTask(id=task_id, prompt=prompt)
        with self._lock:
            self._tasks[task_id] = task

        def _worker():
            task.status = TaskStatus.RUNNING
            task.started_at = time.time()
            try:
                result = agent_fn(prompt)
                task.result = str(result)
                task.status = TaskStatus.DONE
            except Exception as exc:
                task.error = str(exc)
                task.status = TaskStatus.ERROR
            finally:
                task.finished_at = time.time()
                status_icon = "✅" if task.status == TaskStatus.DONE else "❌"
                console.print(
                    f"\n[dim]{status_icon} Background task [bold]{task.short_id}[/bold] "
                    f"finished ({task.elapsed})[/dim]"
                )

        t = threading.Thread(target=_worker, daemon=True, name=f"kratos-bg-{task_id[:8]}")
        t.start()

        console.print(
            f"[bold green]⚡ Background task launched[/bold green] "
            f"[cyan]ID: {task.short_id}[/cyan]\n"
            f"[dim]{prompt[:80]}{'...' if len(prompt) > 80 else ''}[/dim]"
        )
        return task

    def list_tasks(self) -> List[BackgroundTask]:
        """Return all tasks sorted by creation time (newest first)."""
        with self._lock:
            return sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)

    def get_task(self, short_id: str) -> Optional[BackgroundTask]:
        """Lookup a task by its 8-char short ID or full UUID."""
        with self._lock:
            for task in self._tasks.values():
                if task.id == short_id or task.id.startswith(short_id):
                    return task
        return None

    def cancel(self, short_id: str) -> str:
        """Mark a task as cancelled."""
        task = self.get_task(short_id)
        if not task:
            return f"No task found with ID: {short_id}"
        if task.status in (TaskStatus.DONE, TaskStatus.ERROR):
            return f"Task {task.short_id} already finished ({task.status.value})."
        task._cancel_event.set()
        task.status = TaskStatus.CANCELLED
        task.finished_at = time.time()
        return f"Task {task.short_id} marked as cancelled."

    def print_status_table(self):
        """Prints a rich table of all background tasks."""
        tasks = self.list_tasks()
        if not tasks:
            console.print("[dim]No background tasks yet. Use [bold]/bg-run <prompt>[/bold] to launch one.[/dim]")
            return

        table = Table(title="Background Tasks", show_header=True, header_style="bold magenta")
        table.add_column("ID",     style="cyan",  width=10)
        table.add_column("Status", style="white", width=12)
        table.add_column("Elapsed",style="dim",   width=8)
        table.add_column("Prompt", style="white", max_width=50)

        status_colors = {
            TaskStatus.PENDING:   "[yellow]⏳ pending[/yellow]",
            TaskStatus.RUNNING:   "[blue]🔄 running[/blue]",
            TaskStatus.DONE:      "[green]✅ done[/green]",
            TaskStatus.ERROR:     "[red]❌ error[/red]",
            TaskStatus.CANCELLED: "[dim]🚫 cancelled[/dim]",
        }

        for task in tasks:
            table.add_row(
                task.short_id,
                status_colors.get(task.status, task.status.value),
                task.elapsed,
                task.prompt[:50] + ("..." if len(task.prompt) > 50 else ""),
            )
        console.print(table)

    def get_result(self, short_id: str) -> str:
        """Returns the result of a completed task."""
        task = self.get_task(short_id)
        if not task:
            return f"No task found with ID: {short_id}"
        if task.status == TaskStatus.RUNNING:
            return f"Task {task.short_id} is still running ({task.elapsed} elapsed)..."
        if task.status == TaskStatus.ERROR:
            return f"Task {task.short_id} failed:\n{task.error}"
        if task.status == TaskStatus.CANCELLED:
            return f"Task {task.short_id} was cancelled."
        if task.status == TaskStatus.PENDING:
            return f"Task {task.short_id} is pending..."
        return task.result or "(no output)"


# Global singleton
background_runner = BackgroundRunner()
