"""SearXNG meta-search provider for Kratos Search Fabric."""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from typing import Any

from .citations import attach_citations
from .models import SearchResponse, SearchResult
from .provider import SearchProvider

logger = logging.getLogger(__name__)


class SearXNGProvider(SearchProvider):
    """Integrates with self-hosted SearXNG meta-search instances via HTTP JSON API."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (
            base_url
            or os.environ.get("KRATOS_SEARXNG_URL")
            or "http://127.0.0.1:8080"
        ).rstrip("/")

    @property
    def name(self) -> str:
        return "searxng"

    async def is_available(self) -> bool:
        """Pings SearXNG health / test search endpoint."""
        try:
            req = urllib.request.Request(f"{self.base_url}/", headers={"User-Agent": "Kratos/1.0"})
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                return resp.status in (200, 302)
        except Exception:
            return False

    async def search(
        self,
        query: str,
        *,
        category: str | None = None,
        domains: list[str] | None = None,
        language: str | None = None,
        max_results: int = 10,
    ) -> SearchResponse:
        start_time = time.monotonic()
        params: dict[str, Any] = {
            "q": query,
            "format": "json",
        }
        if category:
            params["categories"] = category
        if language:
            params["language"] = language

        # Format URL
        url = f"{self.base_url}/search?{urllib.parse.urlencode(params)}"
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "KratosSearchFabric/1.0",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=8.0) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))

            raw_results = data.get("results", [])
            results: list[SearchResult] = []

            for idx, item in enumerate(raw_results[:max_results], start=1):
                item_url = item.get("url") or ""
                domain = urllib.parse.urlparse(item_url).netloc
                results.append(
                    SearchResult(
                        title=item.get("title") or "Untitled",
                        url=item_url,
                        snippet=item.get("content") or "",
                        source="searxng",
                        engine=item.get("engine"),
                        score=item.get("score"),
                        rank=idx,
                        domain=domain,
                        published_at=item.get("publishedDate"),
                        metadata={"engines": item.get("engines", [])},
                    )
                )

            citations = attach_citations(results)
            latency = (time.monotonic() - start_time) * 1000

            return SearchResponse(
                query=query,
                results=results,
                total_results=len(results),
                provider=self.name,
                latency_ms=latency,
                citations=citations,
            )

        except Exception as e:
            logger.warning(f"[SearXNGProvider] Query failed for '{query}': {e}")
            latency = (time.monotonic() - start_time) * 1000
            return SearchResponse(
                query=query,
                results=[],
                total_results=0,
                provider=self.name,
                latency_ms=latency,
                metadata={"error": str(e)},
            )
