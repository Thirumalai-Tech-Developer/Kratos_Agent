"""Status bar — compact bottom-of-screen status line shown during agent execution."""
from __future__ import annotations

import time
from typing import Dict, Optional

from rich.text import Text


class StatusBar:
    """
    Renders a single-line status bar for the bottom of the live display.

    Format:
      ⚔ gemini-3.6-flash-high  ·  Task 3/7 · Implementing UI · 43%  ·  📊 ~3.8k tokens  ·  8.4s
    """

    def __init__(self, model_name: str = "", session_id: str = "") -> None:
        self.model_name = model_name
        self.session_id = session_id
        self._started_at: float = time.monotonic()
        self._state: str = "idle"
        self._activity: str = ""
        self._usage: Dict[str, int] = {}
        self._tool_name: Optional[str] = None
        self._task_progress: Optional[str] = None

    def reset(self, model_name: str = "", session_id: str = "") -> None:
        if model_name:
            self.model_name = model_name
        if session_id:
            self.session_id = session_id
        self._started_at = time.monotonic()
        self._state = "thinking"
        self._activity = "Thinking"
        self._tool_name = None
        self._task_progress = None

    def set_thinking(self, label: str = "Thinking") -> None:
        self._state = "thinking"
        self._activity = label
        self._tool_name = None

    def set_running_tool(self, tool_name: str) -> None:
        self._state = "running"
        self._activity = f"Running {tool_name}"
        self._tool_name = tool_name

    def set_task_progress(self, current_idx: int, total_count: int, task_name: str, percent: int) -> None:
        if total_count > 0:
            short_title = (task_name[:30] + "…") if len(task_name) > 30 else task_name
            self._task_progress = f"Task {current_idx}/{total_count} · {short_title} · {percent}%"

    def set_success(self) -> None:
        self._state = "success"
        self._activity = "Done"

    def set_done(self) -> None:
        self._state = "done"
        self._activity = "Complete"

    def set_cancelled(self) -> None:
        self._state = "cancelled"
        self._activity = "Cancelled"

    def set_failed(self, reason: str = "") -> None:
        self._state = "failed"
        self._activity = f"Failed: {reason[:40]}" if reason else "Failed"

    def set_usage(self, usage: Dict[str, int]) -> None:
        self._usage = usage

    def set_model(self, name: str) -> None:
        self.model_name = name

    def set_session(self, sid: str) -> None:
        self.session_id = sid

    def _elapsed(self) -> str:
        secs = time.monotonic() - self._started_at
        if secs < 1:
            return f"{secs*1000:.0f}ms"
        return f"{secs:.1f}s"

    def _token_str(self) -> Optional[str]:
        u = self._usage
        if not u:
            return None
        total = (
            u.get("total_tokens")
            or u.get("totalTokens")
            or (
                (u.get("prompt_tokens", 0) or u.get("input_tokens", 0))
                + (u.get("completion_tokens", 0) or u.get("output_tokens", 0))
            )
        )
        if not total:
            return None
        if total >= 1000:
            return f"~{total/1000:.1f}k tokens"
        return f"~{total} tokens"

    def _state_indicator(self) -> tuple[str, str]:
        return {
            "thinking":  ("●", "cyan"),
            "running":   ("▶", "gold1"),
            "success":   ("✓", "green"),
            "done":      ("⚡", "bold white"),
            "idle":      ("⏸", "dim"),
            "cancelled": ("⊘", "red"),
            "failed":    ("✗", "bold red"),
        }.get(self._state, ("●", "white"))

    def render(self) -> Text:
        """Return a Rich Text line for the status bar."""
        sep = Text("  ·  ", style="dim #555")
        t = Text()

        # Model
        t.append("  ⚔ ", style="bold red")
        model_short = self.model_name.replace("gemini-", "").replace("claude-", "")[:28] if self.model_name else "—"
        t.append(model_short, style="bold cyan")

        # Task progress or Session ID
        if self._task_progress:
            t.append_text(sep)
            t.append(self._task_progress, style="bold gold1")
        else:
            t.append_text(sep)
            sid = (self.session_id[:8] + "…") if len(self.session_id) > 8 else (self.session_id or "—")
            t.append("⛓ ", style="dim gold1")
            t.append(sid, style="dim white")

        # Token usage
        tks = self._token_str()
        if tks:
            t.append_text(sep)
            t.append("📊 ", style="dim")
            t.append(tks, style="dim cyan")

        # State indicator
        t.append_text(sep)
        glyph, color = self._state_indicator()
        t.append(f"{glyph} ", style=f"bold {color}")
        t.append(self._activity, style=f"{color}")

        # Elapsed time
        t.append_text(sep)
        t.append(f"⏱ {self._elapsed()}", style="dim")

        t.append("  ", style="")
        return t
