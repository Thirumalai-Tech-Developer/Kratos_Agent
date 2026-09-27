"""Memory storage abstraction with hot caching and TTL."""
from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from kratos_agent.memory.consolidation import consolidate_memories, should_store
from kratos_agent.memory.models import (
    MemoryLayer,
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
)
from kratos_agent.memory.ranking import rank_memories


class MemoryStore:
    """In-memory and file-backed memory store with hot cache (§44)."""

    def __init__(self, storage_path: Path | None = None, cache_ttl: float = 60.0) -> None:
        self.storage_path = storage_path or (Path.cwd() / ".kratos" / "memory_v2.json")
        self.cache_ttl = cache_ttl
        self._records: dict[str, MemoryRecord] = {}
        self._lock = threading.RLock()
        self._cache_max_entries = 128
        self._hot_cache: dict[str, tuple[float, list[MemoryRecord]]] = {}
        self._cache_hits = 0
        self._cache_misses = 0
        self._dirty_accesses = 0
        self._last_save = 0.0
        self._load()

    def _load(self) -> None:
        if self.storage_path.exists():
            try:
                data = json.loads(self.storage_path.read_text(encoding="utf-8"))
                for item in data.get("records", []):
                    rec = MemoryRecord.from_dict(item)
                    self._records[rec.id] = rec
            except Exception as exc:
                logger.debug("Operation error suppressed: %s", exc)

    def save(self) -> None:
        """Atomically persist memory so recent facts survive crashes."""
        try:
            with self._lock:
                self.storage_path.parent.mkdir(parents=True, exist_ok=True)
                data = {"version": 2, "saved_at": time.time(), "records": [r.to_dict() for r in self._records.values()]}
                temp = self.storage_path.with_suffix(self.storage_path.suffix + ".tmp")
                temp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
                os.replace(temp, self.storage_path)
                self._dirty_accesses = 0
                self._last_save = time.time()
        except Exception as exc:
            logger.debug("Operation error suppressed: %s", exc)

    def add(self, record: MemoryRecord) -> None:
        if not should_store(record):
            return
        with self._lock:
            norm = " ".join(record.content.lower().split())
            existing = next((r for r in self._records.values() if " ".join(r.content.lower().split()) == norm), None)
            if existing and existing.id != record.id:
                existing.importance = max(existing.importance, record.importance)
                existing.confidence = max(existing.confidence, record.confidence)
                existing.recency = max(existing.recency, record.recency)
                existing.frequency += 1
            else:
                self._records[record.id] = record
            self.invalidate_cache()
        self.save()

    def get(self, record_id: str) -> MemoryRecord | None:
        return self._records.get(record_id)

    def remove(self, record_id: str) -> bool:
        with self._lock:
            if record_id in self._records:
                del self._records[record_id]
                self.invalidate_cache()
                self.save()
                return True
        return False

    def list_records(
        self,
        scope: MemoryScope | None = None,
        layer: MemoryLayer | None = None,
    ) -> list[MemoryRecord]:
        results = list(self._records.values())
        if scope:
            results = [r for r in results if r.scope == scope]
        if layer:
            results = [r for r in results if r.layer == layer]
        return results

    def query(self, query: MemoryQuery) -> list[MemoryRecord]:
        cache_key = json.dumps({
            "text": query.text, "task": query.task, "application": query.application,
            "project": query.project, "platform": query.platform, "scope": str(query.scope),
            "layer": str(query.layer), "limit": query.limit, "min_confidence": query.min_confidence,
        }, sort_keys=True)
        now = time.time()
        with self._lock:
            cached = self._hot_cache.get(cache_key)
            if cached and (now - cached[0]) < self.cache_ttl:
                self._cache_hits += 1
                return list(cached[1])
            self._cache_misses += 1
            records = list(self._records.values())
            if query.scope:
                records = [r for r in records if r.scope == query.scope]
            if query.layer:
                records = [r for r in records if r.layer == query.layer]
            ranked = rank_memories(query, records)
            top = [rec for rec, _ in ranked[: query.limit]]
            for rec in top:
                rec.last_used = now
                rec.frequency += 1
            self._hot_cache[cache_key] = (now, list(top))
            if len(self._hot_cache) > self._cache_max_entries:
                oldest = sorted(self._hot_cache.items(), key=lambda item: item[1][0])[:len(self._hot_cache)-self._cache_max_entries]
                for key, _ in oldest:
                    self._hot_cache.pop(key, None)
            self._dirty_accesses += len(top)
            dirty = self._dirty_accesses >= 10 or (now - self._last_save) > 30
        if dirty:
            self.save()
        return top

    def invalidate_cache(self) -> None:
        with self._lock:
            self._hot_cache.clear()

    def consolidate(self) -> int:
        initial_count = len(self._records)
        consolidated = consolidate_memories(list(self._records.values()))
        self._records = {r.id: r for r in consolidated}
        self.invalidate_cache()
        self.save()
        return initial_count - len(self._records)

    @property
    def cache_hit_rate(self) -> float:
        total = self._cache_hits + self._cache_misses
        return (self._cache_hits / total * 100.0) if total > 0 else 0.0

    def get_cache_stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "hits": self._cache_hits,
                "misses": self._cache_misses,
                "hit_rate_pct": round(self.cache_hit_rate, 1),
                "cache_size": len(self._hot_cache),
                "cache_max": self._cache_max_entries,
            }

    def export_records(self, export_path: Path | None = None) -> Path:
        """Exports all records to a JSON file."""
        target = export_path or (self.storage_path.parent / f"memory_export_{int(time.time())}.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            data = {
                "version": 2,
                "exported_at": time.time(),
                "records": [r.to_dict() for r in self._records.values()],
            }
            target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return target

    def import_records(self, data_or_path: Path | str | list[dict[str, Any]], merge: bool = True) -> int:
        """Imports memory records from file or dictionary list."""
        imported_records: list[MemoryRecord] = []
        if isinstance(data_or_path, (str, Path)):
            p = Path(data_or_path)
            if not p.exists():
                return 0
            raw = json.loads(p.read_text(encoding="utf-8"))
            items = raw.get("records", raw) if isinstance(raw, dict) else raw
        else:
            items = data_or_path

        for item in items:
            if isinstance(item, dict):
                try:
                    imported_records.append(MemoryRecord.from_dict(item))
                except Exception as exc:
                    logger.debug("Record import parse error: %s", exc)

        with self._lock:
            if merge:
                combined = list(self._records.values()) + imported_records
                consolidated = consolidate_memories(combined)
                self._records = {r.id: r for r in consolidated}
            else:
                self._records = {r.id: r for r in imported_records}
            self.invalidate_cache()
            self.save()
        return len(imported_records)

    def get_health_metrics(self) -> dict[str, Any]:
        """Calculates memory store health and quality indicators."""
        with self._lock:
            recs = list(self._records.values())
            total = len(recs)
            if total == 0:
                return {
                    "total_records": 0,
                    "avg_confidence": 0.0,
                    "high_confidence_pct": 100.0,
                    "layer_counts": {},
                    "health_score": 100.0,
                    "health_status": "OPTIMAL",
                    "cache": self.get_cache_stats(),
                }

            high_conf = sum(1 for r in recs if r.confidence >= 0.70)
            avg_conf = sum(r.confidence for r in recs) / total
            high_conf_pct = (high_conf / total) * 100.0

            layer_counts: dict[str, int] = {}
            for r in recs:
                layer_name = r.layer.value if hasattr(r.layer, "value") else str(r.layer)
                layer_counts[layer_name] = layer_counts.get(layer_name, 0) + 1

            health_score = round(avg_conf * 60.0 + (high_conf_pct * 0.40), 1)
            status = "OPTIMAL" if health_score >= 85.0 else ("HEALTHY" if health_score >= 65.0 else "NEEDS_OPTIMIZATION")

            return {
                "total_records": total,
                "avg_confidence": round(avg_conf, 2),
                "high_confidence_pct": round(high_conf_pct, 1),
                "layer_counts": layer_counts,
                "health_score": health_score,
                "health_status": status,
                "cache": self.get_cache_stats(),
            }
