"""Data models for Kratos Unified Search Fabric."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SearchResult:
    """Normalized search result across all providers (SearXNG, Agent Search, GitHub, Native)."""
    title: str
    url: str
    snippet: Optional[str] = None
    source: str = "web"
    engine: Optional[str] = None
    published_at: Optional[str] = None
    domain: Optional[str] = None
    score: Optional[float] = None
    rank: int = 1
    content: Optional[str] = None
    citation_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    retrieved_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source": self.source,
            "engine": self.engine,
            "published_at": self.published_at,
            "domain": self.domain,
            "score": self.score,
            "rank": self.rank,
            "content": self.content,
            "citation_id": self.citation_id,
            "metadata": self.metadata,
            "retrieved_at": self.retrieved_at,
        }


@dataclass
class SearchResponse:
    """Standardized response from the Search Router or provider."""
    query: str
    results: List[SearchResult] = field(default_factory=list)
    total_results: int = 0
    provider: str = "search_router"
    cached: bool = False
    latency_ms: float = 0.0
    answer: Optional[str] = None
    citations: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "results": [r.to_dict() for r in self.results],
            "total_results": self.total_results,
            "provider": self.provider,
            "cached": self.cached,
            "latency_ms": self.latency_ms,
            "answer": self.answer,
            "citations": self.citations,
            "metadata": self.metadata,
        }


@dataclass
class ExtractedPage:
    """Cleaned page content extracted from a URL."""
    url: str
    title: str
    text: str
    is_safe: bool = True
    status_code: int = 200
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SiteMap:
    """Discovered URLs and endpoints for a site/domain."""
    url: str
    links: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
