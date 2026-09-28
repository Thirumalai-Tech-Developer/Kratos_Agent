"""Audit Plugin - Append-only execution trace logging, session replay, and inspection."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..plugin import HarnessPlugin, PluginMetadata

if TYPE_CHECKING:
    from ..kernel import HarnessKernel

logger = logging.getLogger(__name__)


class AuditPlugin(HarnessPlugin):
    """Provides append-only session event tracing and replay for the Kratos Harness."""

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(
            metadata=PluginMetadata(
                name="audit",
                version="1.0.0",
                description="Append-only event trace recorder, session replay, and inspection.",
                category="audit",
                required_services=[],
                provides_services=["audit"],
            ),
            config=config,
        )
        self._trace_events: list[dict[str, Any]] = []
        self._seq: int = 0
        self.log_file_path: Path | None = None

    def on_register(self) -> None:
        """Called when audit plugin is registered."""
        pass

    def on_start(self) -> None:
        """Called when audit plugin starts."""
        pass

    def on_stop(self) -> None:
        """Called when audit plugin stops."""
        pass

    def on_error(self, exc: Exception) -> None:
        """Called when an error occurs in the audit plugin."""
        super().on_error(exc)

    def on_load(self, kernel: HarnessKernel) -> None:
        super().on_load(kernel)
        kernel.register_service("audit", self)

        # Configure file logging path if configured
        log_dir = self.config.get("log_dir")
        if log_dir:
            dir_path = Path(log_dir)
            dir_path.mkdir(parents=True, exist_ok=True)
            self.log_file_path = dir_path / "harness_trace.jsonl"

    def on_enable(self) -> None:
        super().on_enable()
        if not self.kernel:
            return

        # Hook into kernel events to record audit trace
        def _on_preset(preset: str, **kwargs):
            self.record_event("preset_change", {"preset": preset, **kwargs})

        def _on_plugin_enabled(plugin: str, **kwargs):
            self.record_event("plugin_enabled", {"plugin": plugin, **kwargs})

        def _on_plugin_disabled(plugin: str, **kwargs):
            self.record_event("plugin_disabled", {"plugin": plugin, **kwargs})

        def _on_model_parsed(reasoning: str, content: str, tool_calls: list, **kwargs):
            self.record_event(
                "model_response",
                {
                    "reasoning_length": len(reasoning),
                    "has_reasoning": bool(reasoning),
                    "tool_calls_count": len(tool_calls),
                    "tool_calls": tool_calls,
                },
            )

        self.register_disposable(self.kernel.on("preset_applied", _on_preset))
        self.register_disposable(self.kernel.on("plugin_enabled", _on_plugin_enabled))
        self.register_disposable(self.kernel.on("plugin_disabled", _on_plugin_disabled))
        self.register_disposable(self.kernel.on("model_output_parsed", _on_model_parsed))

    def on_unload(self) -> None:
        if self.kernel:
            self.kernel.unregister_service("audit")
        super().on_unload()

    def record_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Record an append-only event into the harness trace."""
        self._seq += 1
        entry = {
            "seq": self._seq,
            "timestamp": datetime.now(UTC).isoformat(),
            "event_type": event_type,
            "session_id": session_id or "default",
            "payload": payload,
        }
        self._trace_events.append(entry)

        # Write to JSONL if path configured
        if self.log_file_path:
            try:
                with open(self.log_file_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, default=str) + "\n")
            except Exception as e:
                logger.warning(f"[AuditPlugin] Failed to write trace to file: {e}")

        return entry

    def get_trace(
        self,
        session_id: str | None = None,
        event_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Retrieve recent events from the append-only trace."""
        events = self._trace_events
        if session_id:
            events = [e for e in events if e.get("session_id") == session_id]
        if event_type:
            events = [e for e in events if e.get("event_type") == event_type]
        return events[-limit:]

    def export_trace(self, target_path: str, session_id: str | None = None) -> int:
        """Export current session trace to a designated JSON file."""
        events = self._trace_events
        if session_id:
            events = [e for e in events if e.get("session_id") == session_id]

        p = Path(target_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(events, f, indent=2, default=str)

        return len(events)

    def replay_session(self, session_id: str | None = None) -> list[dict[str, Any]]:
        """Replay events in chronological order for session reconstruction."""
        events = self._trace_events
        if session_id:
            events = [e for e in events if e.get("session_id") == session_id]
        return sorted(events, key=lambda x: x["seq"])
