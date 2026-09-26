"""Agent Search provider for Kratos Search Fabric."""
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


class AgentSearchProvider(SearchProvider):
    """Integrates with self-hosted Agent Search engine exposing search, extract, and Tavily-compatible API."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (
            base_url
            or os.environ.get("KRATOS_SEARCH_URL")
            or "http://127.0.0.1:8077"
        ).rstrip("/")
        self._listening: bool = True
        self._last_check: float = 0.0

    @property
    def name(self) -> str:
        return "agent_search"

    def is_listening(self) -> bool:
        """Fast check if the service port is reachable with caching."""
        now = time.monotonic()
        if self._last_check > 0 and (now - self._last_check < 30.0):
            return self._listening

        self._last_check = now
        try:
            import socket
            parsed = urllib.parse.urlparse(self.base_url)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            with socket.create_connection((host, port), timeout=0.2):
                self._listening = True
                return True
        except Exception:
            self._listening = False
            return False

    async def is_available(self) -> bool:
        if not self.is_listening():
            return False
        try:
            req = urllib.request.Request(f"{self.base_url}/health", headers={"User-Agent": "Kratos/1.0"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                return resp.status in (200, 204)
        except Exception:
            self._listening = False
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
        if not self.is_listening():
            return SearchResponse(
                query=query,
                results=[],
                total_results=0,
                provider=self.name,
                latency_ms=0.0,
                metadata={"error": "AgentSearch service port unreachable"},
            )

        payload: dict[str, Any] = {
            "query": query,
            "max_results": max_results,
            "search_depth": "advanced",
        }
        if domains:
            payload["include_domains"] = domains

        url = f"{self.base_url}/search"
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "User-Agent": "KratosSearchFabric/1.0",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=4.0) as resp:
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
                        snippet=item.get("content") or item.get("snippet") or "",
                        source="agent_search",
                        score=float(item.get("score", 1.0)),
                        rank=idx,
                        domain=domain,
                        published_at=item.get("published_date"),
                        content=item.get("raw_content"),
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
                answer=data.get("answer"),
                citations=citations,
            )

        except Exception as e:
            self._listening = False
            self._last_check = time.monotonic()
            logger.debug(f"[AgentSearchProvider] Query failed for '{query}': {e}")
            latency = (time.monotonic() - start_time) * 1000
            return SearchResponse(
                query=query,
                results=[],
                total_results=0,
                provider=self.name,
                latency_ms=latency,
                metadata={"error": str(e)},
            )
