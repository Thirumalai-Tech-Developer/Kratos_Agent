"""Short-term cache with TTL and freshness awareness for Kratos Search Fabric."""
from __future__ import annotations

import re
import threading
import time
from typing import Dict, List, Optional, Tuple

from .models import SearchResponse


class SearchCache:
    """Thread-safe search cache with query normalization, TTL expiration, and freshness bypass."""

    def __init__(self, default_ttl_seconds: float = 300.0) -> None:
        self.default_ttl = default_ttl_seconds
        self._cache: Dict[str, Tuple[float, SearchResponse]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _is_freshness_sensitive(query: str) -> bool:
        """Detects whether a query requires live, uncached results."""
        q = query.lower()
        keywords = ("latest", "today", "current", "now", "recent", "newest", "yesterday", "breaking")
        return any(re.search(r"\b" + re.escape(kw) + r"\b", q) for kw in keywords)

    def _normalize_key(self, query: str, category: Optional[str] = None, mode: str = "standard") -> str:
        q_norm = re.sub(r"\s+", " ", query.strip().lower())
        cat_norm = (category or "general").lower()
        return f"{cat_norm}::{mode}::{q_norm}"

    def get(self, query: str, category: Optional[str] = None, mode: str = "standard") -> Optional[SearchResponse]:
        """Retrieves cached response if valid, unexpired, and not freshness-sensitive."""
        if self._is_freshness_sensitive(query):
            return None

        key = self._normalize_key(query, category, mode)
        now = time.time()
        with self._lock:
            entry = self._cache.get(key)
            if entry:
                expires_at, resp = entry
                if now < expires_at:
                    resp.cached = True
                    return resp
                else:
                    self._cache.pop(key, None)
        return None

    def set(
        self,
        query: str,
        response: SearchResponse,
        category: Optional[str] = None,
        mode: str = "standard",
        ttl: Optional[float] = None,
    ) -> None:
        """Stores response in cache unless freshness sensitive."""
        if self._is_freshness_sensitive(query):
            return

        key = self._normalize_key(query, category, mode)
        duration = ttl if ttl is not None else self.default_ttl
        expires_at = time.time() + duration
        with self._lock:
            self._cache[key] = (expires_at, response)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
