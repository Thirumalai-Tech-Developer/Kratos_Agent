"""Thread-safe terminal renderer supporting NORMAL, DEBUG, and SILENT output modes."""
from __future__ import annotations

import sys
import threading

from kratos_agent.events.models import AgentEvent, EventType
from kratos_agent.output.aggregator import OutputAggregator
from kratos_agent.output.user_output import (
    OutputMode,
    get_user_output_filter,
)


class TerminalRenderer:
    """Synchronizes and renders user-facing output without terminal collisions (§48)."""

    def __init__(self, mode: OutputMode = OutputMode.NORMAL) -> None:
        self.mode = mode
        self._lock = threading.Lock()
        self._filter = get_user_output_filter()
        self._aggregator = OutputAggregator()

    def set_mode(self, mode: OutputMode) -> None:
        self.mode = mode
        self._filter.mode = mode

    def render_event(self, event: AgentEvent) -> None:
        if not self._filter.should_display(event):
            return

        with self._lock:
            if self.mode == OutputMode.DEBUG:
                sys.stdout.write(f"[DEBUG] [{event.type.value}] {event.message}\n")
                sys.stdout.flush()
                return

            # NORMAL mode
            milestone = self._aggregator.aggregate_milestone(event)
            if milestone:
                if event.type == EventType.TASK_COMPLETED:
                    sys.stdout.write(f"\n⚡ Kratos: ✓ {milestone}\n\n")
                elif event.type == EventType.TASK_FAILED:
                    sys.stdout.write(f"\n⚠️ Kratos: ✗ {milestone}\n\n")
                else:
                    sys.stdout.write(f"\n⚡ Kratos: {milestone}\n")
                sys.stdout.flush()

    def print_message(self, message: str, is_final: bool = False, is_error: bool = False) -> None:
        """Direct rendering for high-level agent responses."""
        if self.mode == OutputMode.SILENT and not is_final and not is_error:
            return

        with self._lock:
            prefix = "⚡ Kratos:"
            if is_final:
                prefix = "⚡ Kratos: ✓"
            elif is_error:
                prefix = "⚠️ Kratos: ✗"

            sys.stdout.write(f"\n{prefix} {message}\n")
            sys.stdout.flush()


_terminal_renderer: TerminalRenderer | None = None


def get_terminal_renderer() -> TerminalRenderer:
    global _terminal_renderer
    if _terminal_renderer is None:
        _terminal_renderer = TerminalRenderer()
    return _terminal_renderer
