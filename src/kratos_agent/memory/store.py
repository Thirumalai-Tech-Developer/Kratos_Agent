"""Memory storage abstraction with hot caching and TTL."""
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from kratos_agent.memory.models import MemoryLayer, MemoryQuery, MemoryRecord, MemoryScope
from kratos_agent.memory.ranking import rank_memories
from kratos_agent.memory.consolidation import consolidate_memories, should_store


class MemoryStore:
    """In-memory and file-backed memory store with hot cache (§44)."""

    def __init__(self, storage_path: Optional[Path] = None, cache_ttl: float = 60.0) -> None:
        self.storage_path = storage_path or (Path.cwd() / ".kratos" / "memory_v2.json")
        self.cache_ttl = cache_ttl
        self._records: Dict[str, MemoryRecord] = {}

        # Hot cache: (query_hash, timestamp, results)
        self._hot_cache: Dict[str, Tuple[float, List[MemoryRecord]]] = {}
        self._load()

    def _load(self) -> None:
        if self.storage_path.exists():
            try:
                data = json.loads(self.storage_path.read_text(encoding="utf-8"))
                for item in data.get("records", []):
                    rec = MemoryRecord.from_dict(item)
                    self._records[rec.id] = rec
            except Exception:
                pass

    def save(self) -> None:
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            data = {"records": [r.to_dict() for r in self._records.values()]}
            self.storage_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def add(self, record: MemoryRecord) -> None:
        if should_store(record):
            self._records[record.id] = record
            self.invalidate_cache()

    def get(self, record_id: str) -> Optional[MemoryRecord]:
        return self._records.get(record_id)

    def remove(self, record_id: str) -> bool:
        if record_id in self._records:
            del self._records[record_id]
            self.invalidate_cache()
            return True
        return False

    def list_records(
        self,
        scope: Optional[MemoryScope] = None,
        layer: Optional[MemoryLayer] = None,
    ) -> List[MemoryRecord]:
        results = list(self._records.values())
        if scope:
            results = [r for r in results if r.scope == scope]
        if layer:
            results = [r for r in results if r.layer == layer]
        return results

    def query(self, query: MemoryQuery) -> List[MemoryRecord]:
        cache_key = f"{query.text}|{query.task}|{query.application}|{query.limit}"
        now = time.time()

        if cache_key in self._hot_cache:
            ts, cached_res = self._hot_cache[cache_key]
            if (now - ts) < self.cache_ttl:
                return cached_res

        records = self.list_records(scope=query.scope, layer=query.layer)
        ranked = rank_memories(query, records)
        top = [rec for rec, _ in ranked[: query.limit]]

        self._hot_cache[cache_key] = (now, top)
        return top

    def invalidate_cache(self) -> None:
        self._hot_cache.clear()

    def consolidate(self) -> int:
        initial_count = len(self._records)
        consolidated = consolidate_memories(list(self._records.values()))
        self._records = {r.id: r for r in consolidated}
        self.invalidate_cache()
        self.save()
        return initial_count - len(self._records)
