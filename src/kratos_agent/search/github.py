"""GitHub specialized search provider for Kratos Search Fabric."""
from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from .citations import attach_citations
from .models import SearchResponse, SearchResult
from .provider import SearchProvider

logger = logging.getLogger(__name__)


class GitHubSearchProvider(SearchProvider):
    """Searches GitHub repositories, official sources, and READMEs."""

    @property
    def name(self) -> str:
        return "github"

    async def is_available(self) -> bool:
        return True

    async def search(
        self,
        query: str,
        *,
        category: Optional[str] = None,
        domains: Optional[List[str]] = None,
        language: Optional[str] = None,
        max_results: int = 10,
    ) -> SearchResponse:
        start_time = time.monotonic()
        clean_q = query.replace("github", "").replace("repo", "").strip() or query

        params = {
            "q": clean_q,
            "sort": "stars",
            "order": "desc",
            "per_page": min(max_results, 10),
        }
        url = f"https://api.github.com/search/repositories?{urllib.parse.urlencode(params)}"

        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "KratosSearchFabric/1.0",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            with urllib.request.urlopen(req, timeout=6.0) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))

            items = data.get("items", [])
            results: List[SearchResult] = []

            for idx, item in enumerate(items[:max_results], start=1):
                repo_url = item.get("html_url") or ""
                stars = item.get("stargazers_count", 0)
                desc = item.get("description") or "No description provided."
                lang = item.get("language") or "General"
                full_name = item.get("full_name") or ""

                snippet = f"{desc} [Stars: {stars} | Language: {lang}]"
                results.append(
                    SearchResult(
                        title=f"{full_name} ({stars}★)",
                        url=repo_url,
                        snippet=snippet,
                        source="github",
                        rank=idx,
                        domain="github.com",
                        metadata={
                            "stars": stars,
                            "language": lang,
                            "owner": item.get("owner", {}).get("login"),
                        },
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
            logger.warning(f"[GitHubSearchProvider] Search error: {e}")
            latency = (time.monotonic() - start_time) * 1000
            return SearchResponse(
                query=query,
                results=[],
                total_results=0,
                provider=self.name,
                latency_ms=latency,
                metadata={"error": str(e)},
            )
