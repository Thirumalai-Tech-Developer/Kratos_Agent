"""Milestone aggregator and progress phrase deduplication engine."""
from __future__ import annotations
import re
from typing import List, Optional

from kratos_agent.events.models import AgentEvent, EventType

# Banned repetitive prefixes (§16)
BANNED_PREFIXES = [
    re.compile(r"^(i\s+am|i'm)\s+(currently\s+|now\s+)?(running\s+|starting\s+|checking\s+|confirming\s+)?", re.IGNORECASE),
    re.compile(r"^(i\s+am|i'm)\s+going\s+to\s*", re.IGNORECASE),
    re.compile(r"^let\s+me\s+(just\s+)?(check|gather|look\s+into|see)\s*", re.IGNORECASE),
]

MILESTONES = {
    "browser_open": "Opening the browser.",
    "navigation": "Opening the requested page.",
    "search": "Searching for the requested content.",
    "verification": "Checking the result.",
    "completed": "Done.",
}


class OutputAggregator:
    """Aggregates low-level internal events into concise milestones and sanitizes progress phrases (§15, §16, §46, §47)."""

    def __init__(self) -> None:
        self._seen_messages: List[str] = []

    def sanitize_phrase(self, text: str) -> str:
        """Removes repetitive conversational fluff ('I am currently...', etc.)."""
        cleaned = text.strip()
        for pat in BANNED_PREFIXES:
            cleaned = pat.sub("", cleaned).strip()

        # Capitalize first letter if needed
        if cleaned:
            cleaned = cleaned[0].upper() + cleaned[1:]
        return cleaned

    def is_duplicate(self, message: str) -> bool:
        """Checks if a similar progress message was recently emitted (§46)."""
        clean = message.strip().lower()
        for seen in self._seen_messages[-5:]:
            if clean == seen or (len(clean) > 10 and clean in seen) or (len(seen) > 10 and seen in clean):
                return True
        self._seen_messages.append(clean)
        if len(self._seen_messages) > 20:
            self._seen_messages.pop(0)
        return False

    def aggregate_milestone(self, event: AgentEvent) -> Optional[str]:
        """Maps internal events into user-facing milestone messages."""
        if event.type == EventType.MILESTONE:
            msg = self.sanitize_phrase(event.message)
            if not self.is_duplicate(msg):
                return msg

        if event.type == EventType.TASK_STARTED:
            msg = self.sanitize_phrase(event.message or "Starting task.")
            if not self.is_duplicate(msg):
                return msg

        if event.type == EventType.TASK_COMPLETED:
            return self.sanitize_phrase(event.message or "Done.")

        if event.type == EventType.TASK_FAILED:
            return f"Task failed: {self.sanitize_phrase(event.message)}"

        return None
