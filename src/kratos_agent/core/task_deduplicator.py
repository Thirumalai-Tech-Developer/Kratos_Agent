"""Task deduplication engine preventing rapid repeated execution (§30)."""
from __future__ import annotations

import re
import time


class TaskDeduplicator:
    """Deduplicates incoming user and voice tasks within a temporal sliding window (§30)."""

    DUPLICATE_WINDOW_SECONDS: float = 3.0

    def __init__(self, window_seconds: float = DUPLICATE_WINDOW_SECONDS) -> None:
        self.window_seconds = window_seconds
        # Maps (normalized_task, source) -> timestamp
        self._history: dict[tuple[str, str], float] = {}

    @staticmethod
    def normalize_task(task_description: str) -> str:
        """Normalizes task strings by lowercasing, stripping punctuation, and collapsing whitespace."""
        cleaned = task_description.lower().strip()
        cleaned = re.sub(r"[?!.,;:]", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def is_duplicate(self, task_description: str, source: str = "user_mic") -> bool:
        """Returns True if the identical normalized task was received within the duplicate window."""
        norm = self.normalize_task(task_description)
        key = (norm, source)
        now = time.time()

        last_time = self._history.get(key)
        if last_time is not None and (now - last_time) < self.window_seconds:
            return True

        self._history[key] = now
        # Evict old entries
        cutoff = now - (self.window_seconds * 2)
        self._history = {k: ts for k, ts in self._history.items() if ts >= cutoff}
        return False

    def clear(self) -> None:
        self._history.clear()


_deduplicator: TaskDeduplicator | None = None


def get_task_deduplicator() -> TaskDeduplicator:
    global _deduplicator
    if _deduplicator is None:
        _deduplicator = TaskDeduplicator()
    return _deduplicator
