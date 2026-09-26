from __future__ import annotations

from typing import Any


class EpisodicMemory:
    def __init__(self) -> None:
        self._items: list[dict[str, Any]] = []

    def add(self, item: dict[str, Any]) -> None:
        self._items.append(dict(item))

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        return list(self._items[-limit:])
