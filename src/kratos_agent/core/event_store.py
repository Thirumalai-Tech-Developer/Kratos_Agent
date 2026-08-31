"""Append-only JSONL event storage for recovery, replay, and debug inspection."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .runtime_contracts import RuntimeEvent, json_safe


class EventStore:
    def __init__(self, session_dir: Path) -> None:
        self.session_dir = session_dir
        self.path = session_dir / "events.jsonl"
        self.session_dir.mkdir(parents=True, exist_ok=True)

    def append(self, event: RuntimeEvent) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(json_safe(event), ensure_ascii=False) + "\n")

    def read(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        events = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return events
