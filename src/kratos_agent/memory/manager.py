"""Unified MemoryManager API for Memory Engine V2."""
from __future__ import annotations

import threading
from typing import Any

from kratos_agent.memory.application import ApplicationMemoryStore
from kratos_agent.memory.decay import reinforce_memory
from kratos_agent.memory.errors import ErrorMemoryStore
from kratos_agent.memory.models import (
    MemoryLayer,
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    WorkflowRecord,
)
from kratos_agent.memory.procedural import ProceduralMemoryStore
from kratos_agent.memory.store import MemoryStore
from kratos_agent.memory.working import WorkingMemory


class MemoryManager:
    """Central Memory V2 coordinator exposing full lifecycle API (§37)."""

    def __init__(self) -> None:
        self.store = MemoryStore()
        self.working = WorkingMemory()
        self.procedural = ProceduralMemoryStore()
        self.application = ApplicationMemoryStore()
        self.errors = ErrorMemoryStore()
        self._consolidate_lock = threading.Lock()

    def remember(
        self,
        content: str,
        layer: MemoryLayer = MemoryLayer.SEMANTIC,
        scope: MemoryScope = MemoryScope.GLOBAL,
        importance: float = 0.5,
        confidence: float = 0.8,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> MemoryRecord:
        """Stores a new memory record into the system (§37)."""
        rec = MemoryRecord(
            content=content,
            layer=layer,
            scope=scope,
            importance=importance,
            confidence=confidence,
            metadata=metadata or {},
            tags=tags or [],
        )
        self.store.add(rec)
        return rec

    def recall(
        self,
        text: str,
        task: str | None = None,
        application: str | None = None,
        project: str | None = None,
        scope: MemoryScope | None = None,
        layer: MemoryLayer | None = None,
        limit: int = 5,
        min_confidence: float = 0.20,
    ) -> list[MemoryRecord]:
        """Recalls context-aware ranked memories matching query (§35, §37)."""
        q = MemoryQuery(
            text=text,
            task=task,
            application=application,
            project=project,
            scope=scope,
            layer=layer,
            limit=limit,
            min_confidence=min_confidence,
        )
        return self.store.query(q)

    def search(self, text: str, limit: int = 5) -> list[MemoryRecord]:
        """Quick semantic search for memories."""
        return self.recall(text=text, limit=limit)

    def update(self, record_id: str, content: str | None = None, confidence: float | None = None) -> bool:
        """Updates an existing memory record."""
        rec = self.store.get(record_id)
        if not rec:
            return False
        if content is not None:
            rec.content = content
        if confidence is not None:
            rec.confidence = confidence
        self.store.invalidate_cache()
        self.store.save()
        return True

    def reinforce(self, record_id: str, success: bool = True, bonus: float = 0.1) -> bool:
        """Reinforces or penalizes memory upon verification (§29, §37)."""
        rec = self.store.get(record_id)
        if not rec:
            return False
        reinforce_memory(rec, success=success, bonus=bonus)
        self.store.invalidate_cache()
        return True

    def invalidate(self, record_id: str) -> bool:
        """Invalidates a memory record by lowering confidence to 0."""
        return self.update(record_id, confidence=0.0)

    def forget(self, record_id: str) -> bool:
        """Permanently deletes a memory record."""
        return self.store.remove(record_id)

    def consolidate(self) -> int:
        """Synchronously consolidates and deduplicates memories."""
        return self.store.consolidate()

    def optimize(self, **kwargs: Any) -> Any:
        """Runs full memory maintenance, decay, deduplication, and database optimization."""
        from kratos_agent.memory.maintenance import get_memory_optimizer
        return get_memory_optimizer().run_maintenance(**kwargs)

    def maintain(self, **kwargs: Any) -> Any:
        """Alias for optimize()."""
        return self.optimize(**kwargs)

    def sync_tiers(self) -> tuple[int, int]:
        """Bidirectionally syncs memories between CognitiveMemory and Memory V2."""
        from kratos_agent.memory.maintenance import get_memory_optimizer
        return get_memory_optimizer().sync_tiers()

    def get_health_metrics(self) -> dict[str, Any]:
        """Returns health score, distribution, and cache statistics."""
        return self.store.get_health_metrics()

    def export_memory(self, path: Any = None) -> Any:
        """Exports memory records to JSON."""
        return self.store.export_records(path)

    def import_memory(self, data_or_path: Any, merge: bool = True) -> int:
        """Imports memory records from JSON or dictionaries."""
        return self.store.import_records(data_or_path, merge=merge)

    def async_consolidate(self) -> None:
        """Run at most one consolidation worker at a time."""
        if not self._consolidate_lock.acquire(blocking=False):
            return
        def worker() -> None:
            try:
                self.optimize()
            finally:
                self._consolidate_lock.release()
        threading.Thread(target=worker, name="kratos-memory-consolidate", daemon=True).start()

    def get_workflow(self, trigger_or_name: str) -> WorkflowRecord | None:
        """Retrieves a learned procedural workflow (§24, §37)."""
        return self.procedural.get_workflow(trigger_or_name)

    def save_workflow(
        self,
        name: str,
        trigger: str,
        steps: list[str],
        application: str | None = None,
    ) -> WorkflowRecord:
        """Saves a learned procedural workflow (§24, §37)."""
        return self.procedural.save_workflow(name, trigger, steps, application)

    def get_compact_context(
        self,
        query_text: str,
        task: str | None = None,
        application: str | None = None,
        project: str | None = None,
        limit: int = 4,
    ) -> list[str]:
        """Formats retrieved memory into compact context lines for LLM (§42)."""
        records = self.recall(
            text=query_text,
            task=task,
            application=application,
            project=project,
            limit=limit,
        )
        return [r.content for r in records if r.content]


_memory_manager: MemoryManager | None = None


def get_memory_manager() -> MemoryManager:
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager
