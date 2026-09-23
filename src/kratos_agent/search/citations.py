"""Citation engine for Kratos Search Fabric."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from .models import SearchResult


def attach_citations(results: List[SearchResult]) -> List[Dict[str, Any]]:
    """Assigns sequential [S1], [S2] citation identifiers to search results and returns citation metadata."""
    citations: List[Dict[str, Any]] = []
    for idx, r in enumerate(results, start=1):
        cid = f"S{idx}"
        r.citation_id = cid
        citations.append({
            "citation_id": cid,
            "title": r.title,
            "url": r.url,
            "domain": r.domain,
            "source": r.source,
            "engine": r.engine,
            "excerpt": r.snippet or (r.content[:200] if r.content else ""),
        })
    return citations


def format_search_results_with_citations(results: List[SearchResult]) -> str:
    """Formats search results concisely with citation tags for LLM consumption."""
    if not results:
        return "No search results found."

    lines = ["SEARCH RESULTS:"]
    for r in results:
        cid = r.citation_id or "S?"
        lines.append(f"\n[{cid}] {r.title}")
        lines.append(f"URL: {r.url}")
        if r.domain:
            lines.append(f"Domain: {r.domain}")
        if r.snippet:
            lines.append(f"Excerpt: {r.snippet.strip()}")
        elif r.content:
            lines.append(f"Content: {r.content[:300].strip()}...")
    return "\n".join(lines)
