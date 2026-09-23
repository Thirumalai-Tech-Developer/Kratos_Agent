"""Data models for Kratos Unified Retrieval Fabric."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

RetrievalTarget = Literal["web", "tools", "memory", "docs", "github", "all"]


@dataclass
class RetrievalQuery:
    """Unified query spanning web, tools, memory, docs, and github."""
    text: str
    target: str = "web"  # web, tools, memory, docs, github, all
    mode: str = "fast"  # fast, standard, deep, research
    max_results: int = 10
    context: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass
class RetrievalResult:
    """Consolidated result returned by the RetrievalRouter."""
    target: str
    query: str
    items: List[Any] = field(default_factory=list)
    total: int = 0
    latency_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target": self.target,
            "query": self.query,
            "items": [item.to_dict() if hasattr(item, "to_dict") else item for item in self.items],
            "total": self.total,
            "latency_ms": self.latency_ms,
            "metadata": self.metadata,
        }
