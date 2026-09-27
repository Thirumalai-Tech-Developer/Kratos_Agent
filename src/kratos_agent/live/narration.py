"""Narration manager converting Kratos execution events into natural spoken updates."""
from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from typing import Any

from kratos_agent.core.event_bus import event_bus
from kratos_agent.core.runtime_contracts import RuntimeEvent

logger = logging.getLogger(__name__)

# Secret sanitization patterns
SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password|bearer|omni[_-]?key)\s*(?:[:=]|\bis\b|\s)\s*['\"]?([a-zA-Z0-9_\-\.]{8,})['\"]?"),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"AIza[0-9A-Za-z-_]{20,}"),
]


def sanitize_speech_text(text: str) -> str:
    """Removes API keys, tokens, credentials, and internal markup from spoken text."""
    sanitized = text
    for pat in SECRET_PATTERNS:
        sanitized = pat.sub("[REDACTED]", sanitized)
    # Strip any internal tags
    sanitized = re.sub(r"</?[^>]+>", "", sanitized)
    return sanitized.strip()


class NarrationManager:
    """Subscribes to Kratos event_bus and generates high-signal spoken narrations."""

    def __init__(
        self,
        send_speech_fn: Callable[[str], Any] | None = None,
        min_interval_seconds: float = 4.0,
    ) -> None:
        self.send_speech_fn = send_speech_fn
        self.min_interval = min_interval_seconds
        self.last_speech_time: float = 0.0
        self.last_spoken_message: str = ""
        self.is_active = False

    def set_speech_callback(self, send_speech_fn: Callable[[str], Any]) -> None:
        self.send_speech_fn = send_speech_fn

    def start(self) -> None:
        """Subscribe to the central Kratos event bus."""
        self.is_active = True
        try:
            event_bus.subscribe(self.on_event)
            logger.info("[NarrationManager] Subscribed to Kratos event bus.")
        except Exception as e:
            logger.warning(f"[NarrationManager] Could not subscribe to event bus: {e}")

    def stop(self) -> None:
        """Unsubscribe from the Kratos event bus."""
        self.is_active = False
        try:
            event_bus.unsubscribe(self.on_event)
        except Exception as exc:
            logger.debug("Operation error suppressed: %s", exc)

    def on_event(self, event: RuntimeEvent) -> None:
        """Processes a runtime event and decides whether to narrate."""
        if not self.is_active or not self.send_speech_fn:
            return

        kind = getattr(event.kind, "value", str(event.kind))
        payload = event.payload or {}
        now = time.time()

        narrative: str | None = None
        is_priority = False

        if payload.get("voice_text"):
            narrative = str(payload.get("voice_text"))
            if int(payload.get("voice_priority", 50)) >= 80:
                is_priority = True
        elif kind in ("planning.started", "planning_started"):
            narrative = "Planning the next steps."
        elif kind in ("tool.started", "tool.call_started", "tool_call_started"):
            tool_name = payload.get("name") or payload.get("tool") or "tool"
            narrative = f"Running {tool_name}."
        elif kind == "task.started":
            title = payload.get("title", "")
            if title:
                narrative = f"Starting task: {title[:50]}."
            else:
                narrative = "Executing the next planned task."
        elif kind == "verification.completed":
            passed = payload.get("passed", True)
            narrative = "Verification passed successfully." if passed else "Verification showed remaining issues."
        elif kind == "evidence":
            met = payload.get("met", False)
            detail = payload.get("detail", "")
            if met:
                narrative = f"Verified: {detail}"
            else:
                narrative = f"Outcome not met: {detail}"
            is_priority = True
        elif kind == "false_completion":
            detail = payload.get("correction", "The outcome was checked and is not true.")
            narrative = f"That didn't actually work. {detail[:100]}. Let me look again."
            is_priority = True
        elif kind == "retraction":
            narrative = payload.get("correction", "I was wrong about the previous claim.")
            is_priority = True
        elif kind == "turn.completed":
            ev = payload.get("evidence")
            if ev and ev.get("met"):
                narrative = f"Done — {ev.get('detail', 'task verified')}."
            elif payload.get("status") == "completed" and not payload.get("requires_observable_evidence"):
                narrative = "Task completed."
            else:
                narrative = "Done with the current step."
            is_priority = True
        elif kind in ("turn.failed", "agent.failed"):
            reason = payload.get("error") or payload.get("detail") or "it failed"
            narrative = f"I couldn't finish that — {reason[:100]}."
            is_priority = True
        elif kind == "agent.paused":
            narrative = "Task paused."
            is_priority = True

        if not narrative:
            return

        # Sanity check: forbid unverified success claims
        banned_success = re.search(r"(completed successfully|verified|வெற்றி|முடிவடை)", narrative, re.IGNORECASE)
        ev = payload.get("evidence")
        if banned_success and not (ev and ev.get("met")):
            logger.warning(f"[NarrationManager] Suppressed unverified success claim: {narrative}")
            narrative = "Finished current step."

        # Suppress duplicate consecutive phrases
        if narrative == self.last_spoken_message:
            return

        # Throttle unless priority event
        if not is_priority and (now - self.last_speech_time) < self.min_interval:
            return

        clean_text = sanitize_speech_text(narrative)
        if clean_text:
            self.last_speech_time = now
            self.last_spoken_message = narrative
            logger.info(f"[NarrationManager] Speaking: {clean_text}")
            try:
                self.send_speech_fn(clean_text)
            except Exception as e:
                logger.warning(f"[NarrationManager] Error sending speech: {e}")
