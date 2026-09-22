"""Unified MemoryManager API for Memory Engine V2."""
from __future__ import annotations
import threading
from typing import Any, Dict, List, Optional

from kratos_agent.memory.models import (
    ErrorRecoveryRecord,
    MemoryLayer,
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    WorkflowRecord,
)
from kratos_agent.memory.store import MemoryStore
from kratos_agent.memory.working import WorkingMemory
from kratos_agent.memory.procedural import ProceduralMemoryStore
from kratos_agent.memory.application import ApplicationMemoryStore
from kratos_agent.memory.errors import ErrorMemoryStore
from kratos_agent.memory.decay import reinforce_memory


class MemoryManager:
    """Central Memory V2 coordinator exposing full lifecycle API (§37)."""

    def __init__(self) -> None:
        self.store = MemoryStore()
        self.working = WorkingMemory()
        self.procedural = ProceduralMemoryStore()
        self.application = ApplicationMemoryStore()
        self.errors = ErrorMemoryStore()

    def remember(
        self,
        content: str,
        layer: MemoryLayer = MemoryLayer.SEMANTIC,
        scope: MemoryScope = MemoryScope.GLOBAL,
        importance: float = 0.5,
        confidence: float = 0.8,
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
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
        task: Optional[str] = None,
        application: Optional[str] = None,
        project: Optional[str] = None,
        scope: Optional[MemoryScope] = None,
        layer: Optional[MemoryLayer] = None,
        limit: int = 5,
        min_confidence: float = 0.20,
    ) -> List[MemoryRecord]:
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

    def search(self, text: str, limit: int = 5) -> List[MemoryRecord]:
        """Quick semantic search for memories."""
        return self.recall(text=text, limit=limit)

    def update(self, record_id: str, content: Optional[str] = None, confidence: Optional[float] = None) -> bool:
        """Updates an existing memory record."""
        rec = self.store.get(record_id)
        if not rec:
            return False
        if content is not None:
            rec.content = content
        if confidence is not None:
            rec.confidence = confidence
        self.store.invalidate_cache()
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

    def async_consolidate(self) -> None:
        """Runs consolidation in a background thread to never block execution (§43)."""
        thread = threading.Thread(target=self.store.consolidate, daemon=True)
        thread.start()

    def get_workflow(self, trigger_or_name: str) -> Optional[WorkflowRecord]:
        """Retrieves a learned procedural workflow (§24, §37)."""
        return self.procedural.get_workflow(trigger_or_name)

    def save_workflow(
        self,
        name: str,
        trigger: str,
        steps: List[str],
        application: Optional[str] = None,
    ) -> WorkflowRecord:
        """Saves a learned procedural workflow (§24, §37)."""
        return self.procedural.save_workflow(name, trigger, steps, application)

    def get_compact_context(
        self,
        query_text: str,
        task: Optional[str] = None,
        application: Optional[str] = None,
        project: Optional[str] = None,
        limit: int = 4,
    ) -> List[str]:
        """Formats retrieved memory into compact context lines for LLM (§42)."""
        records = self.recall(
            text=query_text,
            task=task,
            application=application,
            project=project,
            limit=limit,
        )
        return [r.content for r in records if r.content]


_memory_manager: Optional[MemoryManager] = None


def get_memory_manager() -> MemoryManager:
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager
