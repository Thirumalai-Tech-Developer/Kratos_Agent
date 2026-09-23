"""Search router managing execution modes (FAST, STANDARD, DEEP, RESEARCH) and provider selection."""
from __future__ import annotations

import asyncio
import logging
import os
from enum import Enum
from typing import Any, Dict, List, Optional

from .agent_search import AgentSearchProvider
from .cache import SearchCache
from .citations import attach_citations
from .extraction import fetch_and_extract_url
from .github import GitHubSearchProvider
from .hybrid import HybridSearchProvider
from .models import SearchResponse, SearchResult
from .native import NativeWebSearchProvider
from .provider import SearchProvider
from .searxng import SearXNGProvider

logger = logging.getLogger(__name__)


class SearchMode(str, Enum):
    FAST = "fast"
    STANDARD = "standard"
    DEEP = "deep"
    RESEARCH = "research"

    @classmethod
    def from_str(cls, val: str) -> SearchMode:
        try:
            return cls(val.lower())
        except Exception:
            return cls.STANDARD


class SearchRouter:
    """Intelligent router selecting the optimal search provider, mode, caching, and extraction level."""

    def __init__(self) -> None:
        self.cache = SearchCache(default_ttl_seconds=300.0)
        self.searxng = SearXNGProvider()
        self.agent_search = AgentSearchProvider()
        self.github = GitHubSearchProvider()
        self.native = NativeWebSearchProvider()

        # Hybrid aggregator combines primary self-hosted engines with native fallback
        self.hybrid = HybridSearchProvider([self.searxng, self.agent_search, self.native])

    def get_provider_for_query(self, query: str) -> SearchProvider:
        """Determines the appropriate provider based on query intent and configuration."""
        q_lower = query.lower()
        if "github" in q_lower or "repo" in q_lower or "repository" in q_lower:
            return self.github

        env_provider = os.environ.get("KRATOS_SEARCH_PROVIDER", "hybrid").lower()
        if env_provider == "searxng":
            return self.searxng
        elif env_provider == "agent_search":
            return self.agent_search
        elif env_provider == "native":
            return self.native
        return self.hybrid

    async def search(
        self,
        query: str,
        *,
        mode: str = "standard",
        category: Optional[str] = None,
        domains: Optional[List[str]] = None,
        max_results: int = 10,
    ) -> SearchResponse:
        """Routes search query through cache, provider, extraction, and citation pipeline."""
        search_mode = SearchMode.from_str(mode)

        # 1. Check cache (bypassed if freshness-sensitive)
        cached_resp = self.cache.get(query, category=category, mode=search_mode.value)
        if cached_resp is not None:
            return cached_resp

        # 2. Select provider and execute primary search
        provider = self.get_provider_for_query(query)
        num_hits = 5 if search_mode == SearchMode.FAST else max_results
        response = await provider.search(
            query,
            category=category,
            domains=domains,
            max_results=num_hits,
        )

        # Fallback to native if primary provider returned 0 results
        if not response.results and provider.name != "native":
            logger.info(f"[SearchRouter] Provider '{provider.name}' returned 0 hits, falling back to Native provider.")
            response = await self.native.search(query, category=category, domains=domains, max_results=num_hits)

        # 3. Mode-specific enrichment (STANDARD, DEEP, RESEARCH)
        if search_mode in (SearchMode.STANDARD, SearchMode.DEEP, SearchMode.RESEARCH) and response.results:
            # Extract content from top 2-3 results
            extract_count = 1 if search_mode == SearchMode.STANDARD else (3 if search_mode == SearchMode.DEEP else 5)
            for r in response.results[:extract_count]:
                if not r.content and r.url:
                    try:
                        page = await asyncio.to_thread(fetch_and_extract_url, r.url, max_chars=1200)
                        if page.is_safe and page.text:
                            r.content = page.text
                    except Exception as e:
                        logger.debug(f"[SearchRouter] Content extraction skipped for {r.url}: {e}")

        # 4. Attach citations and update cache
        response.citations = attach_citations(response.results)
        self.cache.set(query, response, category=category, mode=search_mode.value)

        return response


# Global SearchRouter singleton
_global_search_router: Optional[SearchRouter] = None


def get_search_router() -> SearchRouter:
    global _global_search_router
    if _global_search_router is None:
        _global_search_router = SearchRouter()
    return _global_search_router
