from __future__ import annotations

from typing import Any, Dict, List


class MemoryRetrieval:
    """Context-only retrieval. It never returns historical commands as executable instructions."""

    def filter_context(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        safe = []
        for item in items:
            if item.get("type") in {"fact", "preference", "knowledge", "context"}:
                safe.append(dict(item))
        return safe
