from __future__ import annotations

from typing import Any


class MemoryRetrieval:
    """Context-only retrieval. It never returns historical commands as executable instructions."""

    def filter_context(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        safe = []
        for item in items:
            if item.get("type") in {"fact", "preference", "knowledge", "context"}:
                safe.append(dict(item))
        return safe
