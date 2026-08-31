"""KratosLiveRenderer — the core live TUI engine.

Renders:
- Top Progress Header (⚔ KRATOS · model · mode)
- Live Goal & PLAN tree with tasks, nested tool activities, and progress summary
- Contextual animated thinking status
- Bottom status bar
"""
from __future__ import annotations

import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from rich.console import Console, Group
from rich.live import Live
from rich.rule import Rule
from rich.text import Text

from kratos_agent.core.approval_mode import approval_gate
from kratos_agent.core.runtime_contracts import EventKind, RuntimeEvent
from kratos_agent.core.event_bus import event_bus
from .events import EventRenderer
from .status_bar import StatusBar
from .stream_printer import (
    is_interactive,
    pipe_print_error,
    pipe_print_response,
    pipe_print_step,
    pipe_print_tool,
)


class KratosLiveRenderer:
    """Wraps KratosRuntime.invoke() with a live event-driven TUI display."""

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self._is_tty = is_interactive()
        self._renderer = EventRenderer(is_tty=self._is_tty)
        self._status_bar = StatusBar()
        self._console = Console(highlight=False, markup=True)
        self._cancel_flag = threading.Event()
        self._live: Optional[Live] = None
        self._last_events: List[Dict[str, Any]] = []
        self.live_mode: bool = self._is_tty

        # Subscribe to central event bus so any published event updates the live TUI
        try:
            event_bus.subscribe(self._hooked_emit)
        except Exception:
            pass

    def cancel(self) -> None:
        """Signal the current agent turn to cancel."""
        self._cancel_flag.set()

    def is_cancelled(self) -> bool:
        return self._cancel_flag.is_set()

    def get_last_steps(self):
        return self._renderer.steps

    def get_last_events(self) -> List[Dict[str, Any]]:
        return list(self._last_events)

    def get_last_plan(self):
        return self._renderer.plan

    def is_chat_mode(self) -> bool:
        return self._renderer.is_chat_mode

    # ── Main Entry Point ───────────────────────────────────────────────────────

    def invoke_with_live(self, messages: List[Dict[str, str]]) -> str:
        """Run runtime.invoke(messages) while rendering a live TUI."""
        self._cancel_flag.clear()
        self._last_events.clear()
        self._renderer.reset()

        session_id = ""
        try:
            mem = self.runtime.memory
            if mem.active_session:
                session_id = mem.active_session.session_id
        except Exception:
            pass

        self._status_bar.reset(
            model_name=self.runtime.model_name,
            session_id=session_id,
        )

        original_emit = self.runtime._emit
        self.runtime._emit = self._hooked_emit

        try:
            if self._is_tty and self.live_mode:
                reply = self._run_with_live(messages)
            else:
                reply = self._run_plain(messages)
        finally:
            self.runtime._emit = original_emit

        return reply

    # ── Live TTY Mode ──────────────────────────────────────────────────────────

    def _run_with_live(self, messages: List[Dict[str, str]]) -> str:
        result_holder: List[str] = []
        exc_holder: List[BaseException] = []

        def _run():
            try:
                r = self.runtime.invoke(messages)
                result_holder.append(r)
            except (KeyboardInterrupt, SystemExit):
                self._cancel_flag.set()
                result_holder.append("")
            except Exception as e:
                exc_holder.append(e)
                result_holder.append("")

        thread = threading.Thread(target=_run, daemon=True)
        self._status_bar.set_thinking(self._renderer.thinking_label)

        with Live(
            self._build_renderable(),
            console=self._console,
            refresh_per_second=4,
            transient=True,
            vertical_overflow="ellipsis",
        ) as live:
            self._live = live
            thread.start()

            try:
                while thread.is_alive():
                    # Sync plan progress to status bar
                    if self._renderer.plan and self._renderer.plan.tasks:
                        plan = self._renderer.plan
                        active_idx = plan.get_active_index() + 1
                        active_task = plan.get_active_task()
                        tname = active_task.title if active_task else (plan.tasks[0].title if plan.tasks else "")
                        self._status_bar.set_task_progress(active_idx, plan.total_count, tname, plan.progress_percent)

                    live.update(self._build_renderable())
                    time.sleep(0.12)
                    if self._cancel_flag.is_set():
                        break
            except KeyboardInterrupt:
                self._cancel_flag.set()
                self._status_bar.set_cancelled()
                live.update(self._build_renderable())

            thread.join(timeout=2.0)
            self._status_bar.set_done()
            live.update(self._build_renderable())
            self._live = None

        if exc_holder:
            raise exc_holder[0]

        return result_holder[0] if result_holder else ""

    def _build_renderable(self) -> Group:
        """Build the clean live renderable layout."""
        parts = []

        # 1. Top Header
        mode_str = approval_gate.mode.value.upper()
        state_badge = f" · {self._renderer.plan.state.badge}" if (self._renderer.plan and self._renderer.plan.state) else ""
        header_title = f"[bold red]⚔ KRATOS[/bold red] · [bold cyan]{self.runtime.model_name}[/bold cyan] · [bold gold1]{mode_str}[/bold gold1]{state_badge}"
        parts.append(Rule(
            title=header_title,
            style="dim red",
            align="center",
        ))

        # 2. Live PLAN Tree (Goal + Tasks + Nested Substeps + Progress)
        if not self._renderer.is_chat_mode:
            plan_tree = self._renderer.render_plan_tree()
            if plan_tree:
                parts.append(plan_tree)

        # 3. Contextual Thinking Spinner
        parts.append(self._renderer.render_thinking_line())

        # 4. Bottom Status Bar
        parts.append(Rule(style="dim #333"))
        parts.append(self._status_bar.render())

        return Group(*parts)

    # ── Plain / Pipe Mode ──────────────────────────────────────────────────────

    def _run_plain(self, messages: List[Dict[str, str]]) -> str:
        pipe_print_step("THINKING", "Kratos is thinking…")
        try:
            reply = self.runtime.invoke(messages)
            pipe_print_step("DONE", "Turn complete", elapsed=self._renderer.total_elapsed())
            return reply
        except (KeyboardInterrupt, SystemExit):
            pipe_print_step("CANCELLED", "Interrupted by user")
            return ""
        except Exception as e:
            pipe_print_error(str(e))
            raise

    # ── Event Interception Hook ────────────────────────────────────────────────

    def _hooked_emit(self, event: RuntimeEvent) -> None:
        try:
            self.runtime._event_store.append(event)
        except Exception:
            pass

        try:
            self._last_events.append(event.to_dict())
        except Exception:
            pass

        kind = event.kind
        payload = event.payload

        if kind == EventKind.AGENT_STARTED:
            self._renderer.on_agent_started(payload)
        elif kind == EventKind.UNDERSTANDING_STARTED:
            self._renderer.on_understanding_started(payload)
            self._status_bar.set_thinking("Understanding")
        elif kind == EventKind.PLANNING_STARTED:
            self._renderer.on_planning_started(payload)
            self._status_bar.set_thinking("Planning")
        elif kind == EventKind.PLAN_CREATED:
            self._renderer.on_plan_created(payload)
        elif kind == EventKind.PLAN_UPDATED:
            self._renderer.on_plan_updated(payload)
        elif kind == EventKind.TASK_STARTED:
            self._renderer.on_task_started(payload)
            self._status_bar.set_thinking(payload.get("title", "Implementing"))
        elif kind == EventKind.TASK_UPDATED:
            self._renderer.on_task_updated(payload)
        elif kind == EventKind.TASK_COMPLETED:
            self._renderer.on_task_completed(payload)
        elif kind == EventKind.TASK_FAILED:
            self._renderer.on_task_failed(payload)
        elif kind == EventKind.VERIFICATION_STARTED:
            self._renderer.on_verification_started(payload)
            self._status_bar.set_thinking("Verifying")
        elif kind == EventKind.VERIFICATION_COMPLETED:
            self._renderer.on_verification_completed(payload)
        elif kind == EventKind.TURN_STARTED:
            pass
        elif kind == EventKind.REQUEST_ASSEMBLED:
            self._renderer.on_thinking_started()
            self._status_bar.set_thinking("Sending request…")
        elif kind == EventKind.MODEL_RESPONSE:
            self._renderer.on_model_response(payload)
            usage = payload.get("usage") or {}
            self._status_bar.set_usage(usage)
        elif kind in (EventKind.TOOL_REQUESTED, EventKind.TOOL_CALL_STARTED):
            self._renderer.on_tool_requested(payload)
            name = payload.get("name", "tool")
            self._status_bar.set_running_tool(name)
        elif kind == EventKind.TOOL_COMPLETED:
            self._renderer.on_tool_completed(payload, failed=False)
            self._status_bar.set_thinking("Processing…")
        elif kind == EventKind.TOOL_FAILED:
            self._renderer.on_tool_completed(payload, failed=True)
            self._status_bar.set_thinking("Recovering…")
        elif kind in (EventKind.TURN_COMPLETED, EventKind.AGENT_COMPLETED):
            if "plan" in payload and isinstance(payload["plan"], dict):
                self._renderer.on_plan_updated(payload["plan"])
            self._status_bar.set_done()
        elif kind in (EventKind.TURN_FAILED, EventKind.AGENT_FAILED):
            if "plan" in payload and isinstance(payload["plan"], dict):
                self._renderer.on_plan_updated(payload["plan"])
            self._status_bar.set_failed(payload.get("error", ""))

        if self._live is not None:
            try:
                self._live.update(self._build_renderable())
            except Exception:
                pass
