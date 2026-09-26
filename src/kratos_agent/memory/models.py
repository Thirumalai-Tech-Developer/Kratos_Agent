"""Core data models for Memory Engine V2."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MemoryScope(str, Enum):
    TASK = "TASK"
    SESSION = "SESSION"
    PROJECT = "PROJECT"
    APPLICATION = "APPLICATION"
    USER = "USER"
    GLOBAL = "GLOBAL"
    WORKFLOW = "WORKFLOW"


class MemoryLayer(str, Enum):
    """Hierarchical memory layers (§30)."""
    WORKING = "WORKING"
    TASK = "TASK"
    SESSION = "SESSION"
    LONG_TERM = "LONG_TERM"
    TOOL = "TOOL"
    ERROR = "ERROR"
    # Backwards-compatible aliases
    EPISODIC = "EPISODIC"
    SEMANTIC = "SEMANTIC"
    PROCEDURAL = "PROCEDURAL"
    APPLICATION = "APPLICATION"


class MemoryPriority(int, Enum):
    """Observation priority ladder (§33)."""
    CURRENT_OBSERVATION = 5
    CURRENT_TASK_STATE = 4
    RECENT_VERIFIED_MEMORY = 3
    LONG_TERM_MEMORY = 2
    MODEL_ASSUMPTION = 1


@dataclass
class MemoryRecord:
    """Represents a discrete memory unit across any layer and scope (§30, §32)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    layer: MemoryLayer = MemoryLayer.SEMANTIC
    scope: MemoryScope = MemoryScope.GLOBAL
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    importance: float = 0.5
    confidence: float = 0.8
    recency: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    frequency: int = 1
    utility: float = 0.5
    source: str = "agent"
    success_count: int = 1
    failure_count: int = 0
    decay_rate: float = 0.01  # Per day
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "layer": self.layer.value if isinstance(self.layer, MemoryLayer) else str(self.layer),
            "scope": self.scope.value if isinstance(self.scope, MemoryScope) else str(self.scope),
            "content": self.content,
            "metadata": self.metadata,
            "importance": self.importance,
            "confidence": self.confidence,
            "recency": self.recency,
            "frequency": self.frequency,
            "utility": self.utility,
            "source": self.source,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "decay_rate": self.decay_rate,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryRecord:
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            layer=MemoryLayer(data.get("layer", "SEMANTIC")),
            scope=MemoryScope(data.get("scope", "GLOBAL")),
            content=data.get("content", ""),
            metadata=data.get("metadata", {}),
            importance=float(data.get("importance", 0.5)),
            confidence=float(data.get("confidence", 0.8)),
            recency=float(data.get("recency", time.time())),
            frequency=int(data.get("frequency", 1)),
            utility=float(data.get("utility", 0.5)),
            source=data.get("source", "agent"),
            success_count=int(data.get("success_count", 1)),
            failure_count=int(data.get("failure_count", 0)),
            decay_rate=float(data.get("decay_rate", 0.01)),
            tags=data.get("tags", []),
        )


@dataclass
class MemoryQuery:
    """Context-aware query container for memory retrieval."""
    text: str
    task: str | None = None
    application: str | None = None
    platform: str | None = None
    project: str | None = None
    scope: MemoryScope | None = None
    layer: MemoryLayer | None = None
    limit: int = 5
    min_confidence: float = 0.20


@dataclass
class WorkflowRecord:
    """Procedural memory workflow specification."""
    name: str
    trigger: str
    steps: list[str]
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    application: str | None = None
    success_count: int = 1
    failure_count: int = 0
    confidence: float = 0.90

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "trigger": self.trigger,
            "steps": self.steps,
            "application": self.application,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowRecord:
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            name=data.get("name", ""),
            trigger=data.get("trigger", ""),
            steps=data.get("steps", []),
            application=data.get("application"),
            success_count=int(data.get("success_count", 1)),
            failure_count=int(data.get("failure_count", 0)),
            confidence=float(data.get("confidence", 0.90)),
        )


@dataclass
class ErrorRecoveryRecord:
    """Error and recovery strategy memory record."""
    error: str
    solution: str
    context: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    success_count: int = 1
    confidence: float = 0.85

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "error": self.error,
            "context": self.context,
            "solution": self.solution,
            "success_count": self.success_count,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ErrorRecoveryRecord:
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            error=data.get("error", ""),
            context=data.get("context", ""),
            solution=data.get("solution", ""),
            success_count=int(data.get("success_count", 1)),
            confidence=float(data.get("confidence", 0.85)),
        )
