"""Hybrid multi-engine aggregator, deduplicator, and ranker for Kratos Search Fabric."""
from __future__ import annotations

import asyncio
import logging
import re
import time
import urllib.parse

from .citations import attach_citations
from .models import SearchResponse, SearchResult
from .provider import SearchProvider

logger = logging.getLogger(__name__)

# Trusted domain score boosts
TRUSTED_DOMAIN_PATTERNS = [
    (re.compile(r"(?i)\bdocs\."), 1.4),
    (re.compile(r"(?i)\.org$"), 1.2),
    (re.compile(r"(?i)\.edu$"), 1.3),
    (re.compile(r"(?i)\.gov$"), 1.4),
    (re.compile(r"(?i)github\.com"), 1.3),
    (re.compile(r"(?i)python\.org"), 1.5),
    (re.compile(r"(?i)mozilla\.org"), 1.5),
    (re.compile(r"(?i)microsoft\.com"), 1.4),
    (re.compile(r"(?i)google\.com"), 1.3),
    (re.compile(r"(?i)wikipedia\.org"), 1.2),
    (re.compile(r"(?i)stackoverflow\.com"), 1.1),
]

# Tracking parameters to strip during URL normalization
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "ref", "source", "ref_src", "spm"
}


def normalize_url(raw_url: str) -> str:
    """Normalizes URL scheme, host, and removes tracking query parameters for clean deduplication."""
    try:
        parsed = urllib.parse.urlparse(raw_url.strip())
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/")

        # Filter query params
        q_pairs = urllib.parse.parse_qsl(parsed.query)
        filtered_q = [(k, v) for k, v in q_pairs if k.lower() not in TRACKING_PARAMS]
        clean_query = urllib.parse.urlencode(filtered_q)

        return urllib.parse.urlunparse((scheme, netloc, path, "", clean_query, ""))
    except Exception:
        return raw_url.strip().lower()


def rank_and_score_results(results: list[SearchResult], query: str) -> list[SearchResult]:
    """Ranks results based on relevance to query tokens, domain trust, and freshness."""
    q_tokens = set(re.findall(r"\w+", query.lower()))

    for r in results:
        base_score = r.score if r.score is not None else 1.0

        # Title match boost
        t_tokens = set(re.findall(r"\w+", (r.title or "").lower()))
        overlap = len(q_tokens.intersection(t_tokens))
        base_score += overlap * 0.3

        # Domain trust boost
        domain = (r.domain or "").lower()
        for pattern, boost in TRUSTED_DOMAIN_PATTERNS:
            if pattern.search(domain):
                base_score *= boost
                break

        r.score = round(base_score, 3)

    # Sort descending by computed score
    results.sort(key=lambda x: x.score or 0.0, reverse=True)
    for idx, r in enumerate(results, start=1):
        r.rank = idx
    return results


class HybridSearchProvider(SearchProvider):
    """Aggregates multiple search providers with parallel queries, canonical deduplication, and ranking."""

    def __init__(self, providers: list[SearchProvider]) -> None:
        self.providers = providers

    @property
    def name(self) -> str:
        return "hybrid"

    async def is_available(self) -> bool:
        return any(await p.is_available() for p in self.providers)

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

        # Query listening/available providers in parallel
        active_providers = [
            p for p in self.providers
            if not hasattr(p, "is_listening") or p.is_listening()
        ]
        if not active_providers:
            active_providers = self.providers

        tasks = [
            p.search(query, category=category, domains=domains, language=language, max_results=max_results)
            for p in active_providers
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        combined_results: list[SearchResult] = []
        seen_urls: set[str] = set()

        for resp in responses:
            if isinstance(resp, SearchResponse):
                for item in resp.results:
                    norm_url = normalize_url(item.url)
                    if norm_url not in seen_urls:
                        seen_urls.add(norm_url)
                        combined_results.append(item)

        # Rank and deduplicate
        ranked = rank_and_score_results(combined_results, query)[:max_results]
        citations = attach_citations(ranked)
        latency = (time.monotonic() - start_time) * 1000

        return SearchResponse(
            query=query,
            results=ranked,
            total_results=len(ranked),
            provider=self.name,
            latency_ms=latency,
            citations=citations,
        )
