"""Unified Self-Hosted Search Fabric for Kratos Agent."""
from .agent_search import AgentSearchProvider
from .cache import SearchCache
from .citations import attach_citations, format_search_results_with_citations
from .extraction import fetch_and_extract_url, is_url_safe, sanitize_web_content
from .github import GitHubSearchProvider
from .hybrid import HybridSearchProvider
from .models import ExtractedPage, SearchResponse, SearchResult, SiteMap
from .native import NativeWebSearchProvider
from .provider import SearchProvider
from .router import SearchMode, SearchRouter, get_search_router
from .searxng import SearXNGProvider
from .tavily import TavilySearchProvider

__all__ = [
    "AgentSearchProvider",
    "ExtractedPage",
    "GitHubSearchProvider",
    "HybridSearchProvider",
    "NativeWebSearchProvider",
    "SearXNGProvider",
    "SearchCache",
    "SearchMode",
    "SearchProvider",
    "SearchResponse",
    "SearchResult",
    "SearchRouter",
    "SiteMap",
    "TavilySearchProvider",
    "attach_citations",
    "fetch_and_extract_url",
    "format_search_results_with_citations",
    "get_search_router",
    "is_url_safe",
    "sanitize_web_content",
]
