"""Unified Self-Hosted Search Fabric for Kratos Agent."""
from .models import ExtractedPage, SearchResponse, SearchResult, SiteMap
from .provider import SearchProvider
from .searxng import SearXNGProvider
from .tavily import TavilySearchProvider
from .agent_search import AgentSearchProvider
from .github import GitHubSearchProvider
from .native import NativeWebSearchProvider
from .hybrid import HybridSearchProvider
from .router import SearchMode, SearchRouter, get_search_router
from .cache import SearchCache
from .citations import attach_citations, format_search_results_with_citations
from .extraction import fetch_and_extract_url, is_url_safe, sanitize_web_content

__all__ = [
    "ExtractedPage",
    "SearchResponse",
    "SearchResult",
    "SiteMap",
    "SearchProvider",
    "SearXNGProvider",
    "TavilySearchProvider",
    "AgentSearchProvider",
    "GitHubSearchProvider",
    "NativeWebSearchProvider",
    "HybridSearchProvider",
    "SearchMode",
    "SearchRouter",
    "get_search_router",
    "SearchCache",
    "attach_citations",
    "format_search_results_with_citations",
    "fetch_and_extract_url",
    "is_url_safe",
    "sanitize_web_content",
]
