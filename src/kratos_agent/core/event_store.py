"""Append-only JSONL and Cloudflare D1 database event storage for recovery, replay, and trace inspection."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .d1_client import D1DatabaseClient, d1_db
from .runtime_contracts import EventKind, RuntimeEvent, json_safe


class EventStore:
    """Stores agentic runtime events in Cloudflare D1 database and local JSONL fallback."""

    def __init__(
        self,
        session_dir: Path,
        session_id: Optional[str] = None,
        db: Optional[D1DatabaseClient] = None,
        d1_db: Optional[D1DatabaseClient] = None,
    ) -> None:
        self.session_dir = session_dir
        self.session_id = session_id or session_dir.name
        self.path = session_dir / "events.jsonl"
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.db = d1_db or db
        if self.db is None:
            from .d1_client import d1_db as default_d1
            self.db = default_d1

    def append(self, event: RuntimeEvent) -> None:
        """Appends a runtime event to local JSONL and Cloudflare D1 database."""
        if event.kind == EventKind.MODEL_CHUNK or getattr(event.kind, "value", str(event.kind)) == "model.chunk":
            return

        # 1. Local JSONL write for immediate file trace
        try:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(json_safe(event), ensure_ascii=False) + "\n")
        except Exception:
            pass

        # 2. Cloudflare D1 database persistence
        try:
            event_id = f"evt_{uuid.uuid4().hex[:12]}"
            kind_str = getattr(event.kind, "value", str(event.kind))
            turn_id = getattr(event, "turn_id", "") or ""
            ts = float(getattr(event, "timestamp", time.time()))
            payload_json = json.dumps(json_safe(event.payload), ensure_ascii=False)

            self.db.execute(
                """INSERT INTO agentic_events (id, session_id, turn_id, kind, timestamp, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [event_id, self.session_id, turn_id, kind_str, ts, payload_json],
            )
        except Exception:
            pass

    def read(self) -> List[Dict[str, Any]]:
        """Reads all events for this session from Cloudflare D1, falling back to local JSONL."""
        # Try reading from D1 database first
        try:
            rows = self.db.execute(
                "SELECT * FROM agentic_events WHERE session_id = ? ORDER BY timestamp ASC",
                [self.session_id],
            )
            if rows:
                events = []
                for r in rows:
                    raw_payload = r.get("payload_json")
                    try:
                        payload = json.loads(raw_payload) if raw_payload else {}
                    except Exception:
                        payload = {"raw": raw_payload}
                    events.append({
                        "id": r.get("id"),
                        "session_id": r.get("session_id"),
                        "turn_id": r.get("turn_id"),
                        "kind": r.get("kind"),
                        "timestamp": r.get("timestamp"),
                        "payload": payload,
                    })
                return events
        except Exception:
            pass

        # Fallback to local JSONL file
        if not self.path.exists():
            return []
        events = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return events
