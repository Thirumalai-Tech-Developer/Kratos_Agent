"""Abstract base class and registry for search providers in Kratos Search Fabric."""
from __future__ import annotations

from abc import ABC, abstractmethod

from .models import ExtractedPage, SearchResponse, SiteMap


class SearchProvider(ABC):
    """Abstract interface defining search, extraction, and sitemap capabilities."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the provider (e.g. searxng, agent_search, github, native)."""

    @abstractmethod
    async def is_available(self) -> bool:
        """Checks if the backend search service is reachable."""

    @abstractmethod
    async def search(
        self,
        query: str,
        *,
        category: str | None = None,
        domains: list[str] | None = None,
        language: str | None = None,
        max_results: int = 10,
    ) -> SearchResponse:
        """Performs search and returns normalized SearchResponse."""

    async def extract(self, url: str, *, deep: bool = False) -> ExtractedPage:
        """Extracts cleaned page content from URL."""
        from .extraction import fetch_and_extract_url
        return fetch_and_extract_url(url)

    async def map_site(self, url: str) -> SiteMap:
        """Discovers key endpoints and URLs from a base domain."""
        return SiteMap(url=url, links=[url])
