from __future__ import annotations

from typing import Any, Dict, List


class SemanticMemory:
    def __init__(self) -> None:
        self._items: Dict[str, Dict[str, Any]] = {}

    def put(self, key: str, value: Dict[str, Any]) -> None:
        self._items[key] = dict(value)

    def get(self, key: str) -> Dict[str, Any] | None:
        return self._items.get(key)

    def all(self) -> List[Dict[str, Any]]:
        return list(self._items.values())
