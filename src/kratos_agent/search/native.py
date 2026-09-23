"""Native web search provider (DuckDuckGo + Wikipedia) for Kratos Search Fabric."""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from .citations import attach_citations
from .models import SearchResponse, SearchResult
from .provider import SearchProvider

logger = logging.getLogger(__name__)


class NativeWebSearchProvider(SearchProvider):
    """Reliable fallback web search provider using DuckDuckGo and Wikipedia."""

    @property
    def name(self) -> str:
        return "native"

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
        results: List[SearchResult] = []

        # 1. Try DuckDuckGo
        try:
            from ddgs import DDGS
            with DDGS() as ddgs:
                ddg_hits = list(ddgs.text(query, max_results=max_results))
                for idx, r in enumerate(ddg_hits, start=1):
                    href = r.get("href", "")
                    domain = urllib.parse.urlparse(href).netloc
                    results.append(
                        SearchResult(
                            title=r.get("title", "Untitled"),
                            url=href,
                            snippet=r.get("body", ""),
                            source="duckduckgo",
                            engine="ddgs",
                            rank=idx,
                            domain=domain,
                        )
                    )
        except Exception as e:
            logger.debug(f"[NativeWebSearch] DuckDuckGo search attempt failed: {e}")

        # 2. If no results, fallback to Wikipedia API
        if not results:
            try:
                wiki_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote_plus(query)}&format=json"
                req = urllib.request.Request(wiki_url, headers={"User-Agent": "KratosSearchFabric/1.0"})
                with urllib.request.urlopen(req, timeout=5.0) as resp:
                    data = json.loads(resp.read().decode("utf-8", errors="replace"))

                items = data.get("query", {}).get("search", [])
                for idx, item in enumerate(items[:max_results], start=1):
                    title = item.get("title", "")
                    clean_snip = re.sub(r"<[^>]+>", "", item.get("snippet", ""))
                    page_url = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
                    results.append(
                        SearchResult(
                            title=title,
                            url=page_url,
                            snippet=clean_snip,
                            source="wikipedia",
                            engine="wikipedia",
                            rank=idx,
                            domain="wikipedia.org",
                        )
                    )
            except Exception as e:
                logger.debug(f"[NativeWebSearch] Wikipedia fallback failed: {e}")

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
