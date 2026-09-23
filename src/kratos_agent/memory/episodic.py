from __future__ import annotations

from typing import Any, Dict, List


class EpisodicMemory:
    def __init__(self) -> None:
        self._items: List[Dict[str, Any]] = []

    def add(self, item: Dict[str, Any]) -> None:
        self._items.append(dict(item))

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        return list(self._items[-limit:])
