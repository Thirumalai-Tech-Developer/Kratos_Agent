from __future__ import annotations

from typing import Any


class SemanticMemory:
    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}

    def put(self, key: str, value: dict[str, Any]) -> None:
        self._items[key] = dict(value)

    def get(self, key: str) -> dict[str, Any] | None:
        return self._items.get(key)

    def all(self) -> list[dict[str, Any]]:
        return list(self._items.values())
