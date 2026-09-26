"""Data models for Kratos Unified Retrieval Fabric."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

RetrievalTarget = Literal["web", "tools", "memory", "docs", "github", "all"]


@dataclass
class RetrievalQuery:
    """Unified query spanning web, tools, memory, docs, and github."""
    text: str
    target: str = "web"  # web, tools, memory, docs, github, all
    mode: str = "fast"  # fast, standard, deep, research
    max_results: int = 10
    context: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass
class RetrievalResult:
    """Consolidated result returned by the RetrievalRouter."""
    target: str
    query: str
    items: list[Any] = field(default_factory=list)
    total: int = 0
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "query": self.query,
            "items": [item.to_dict() if hasattr(item, "to_dict") else item for item in self.items],
            "total": self.total,
            "latency_ms": self.latency_ms,
            "metadata": self.metadata,
        }
