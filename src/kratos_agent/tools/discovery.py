"""Dynamic hybrid tool discovery and ranking for Kratos Agent.

Reduces the 181+ tool catalog into the top 5-15 most relevant candidate tools
for any given task, eliminating model confusion and context bloat.
"""
from __future__ import annotations

import re
from typing import Any

from .index import ToolIndex, ToolMetadata, get_tool_index


class ToolSearch:
    """Hybrid tool discovery engine combining keyword matching, token similarity, and context affinity."""

    def __init__(self, index: ToolIndex | None = None) -> None:
        self.index = index or get_tool_index()

    def search(
        self,
        query: str,
        context: dict[str, Any] | None = None,
        max_results: int = 15,
        min_results: int = 5,
    ) -> list[ToolMetadata]:
        """Discovers and ranks candidate tools for a user query and application context."""
        ctx = context or {}
        q_clean = query.lower().strip()
        q_tokens = set(re.findall(r"\w+", q_clean))

        # Context indicators
        active_app = str(ctx.get("app") or ctx.get("active_window", "")).lower()
        active_browser = "chrome" in active_app or "edge" in active_app or "browser" in active_app

        scored_tools: list[tuple[float, ToolMetadata]] = []

        for meta in self.index.list_all():
            score = 0.0
            n_lower = meta.name.lower()
            desc_lower = meta.description.lower()
            cat = meta.category.upper()

            # 1. Exact name or token match in tool name
            if n_lower in q_clean:
                score += 5.0
            for t in q_tokens:
                if t in n_lower:
                    score += 2.0

            # 2. Keywords match
            for kw in meta.keywords:
                if kw.lower() in q_clean:
                    score += 1.5

            # 3. Description token overlap
            d_tokens = set(re.findall(r"\w+", desc_lower))
            overlap = len(q_tokens.intersection(d_tokens))
            score += overlap * 0.4

            # 4. Contextual Category Affinity
            if any(w in q_clean for w in ("browser", "youtube", "url", "web", "chrome", "website", "navigate")):
                if cat == "BROWSER":
                    score += 3.0
                elif cat == "COMPUTER":
                    score += 1.0
                elif cat in ("MEMORY", "SYSTEM", "FILES"):
                    score -= 1.0

            if any(w in q_clean for w in ("file", "code", "edit", "write", "read", "grep", "search_symbol", "script")):
                if cat in ("FILES", "CODE"):
                    score += 3.0
                elif cat == "BROWSER":
                    score -= 1.0

            if any(w in q_clean for w in ("search", "find", "who is", "what is", "latest", "lookup")):
                if cat == "SEARCH" or "search" in n_lower:
                    score += 3.0

            # 5. Core essential tools guarantee baseline presence
            if meta.name in ("read_file", "write_file", "edit_file", "run_terminal_command", "list_directory", "grep_search"):
                score += 0.5

            if score > 0:
                scored_tools.append((score, meta))

        # Sort descending by score
        scored_tools.sort(key=lambda x: x[0], reverse=True)

        # Select top candidates (bounded between min_results and max_results)
        candidates = [item[1] for item in scored_tools[:max_results]]

        # Fallback to essential general tools if nothing matched
        if len(candidates) < min_results:
            essential = ["read_file", "write_file", "edit_file", "run_terminal_command", "list_directory"]
            for name in essential:
                m = self.index.get(name)
                if m and m not in candidates:
                    candidates.append(m)
                if len(candidates) >= max_results:
                    break

        return candidates[:max_results]

    def get_tool_schemas(
        self,
        query: str,
        context: dict[str, Any] | None = None,
        max_results: int = 15,
    ) -> list[dict[str, Any]]:
        """Returns JSON schema definitions for the top discovered tools."""
        tools = self.search(query, context=context, max_results=max_results)
        schemas = []
        for t in tools:
            schemas.append({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
                "category": t.category,
            })
        return schemas


# Global ToolSearch singleton
_global_tool_search: ToolSearch | None = None


def get_tool_search() -> ToolSearch:
    global _global_tool_search
    if _global_tool_search is None:
        _global_tool_search = ToolSearch()
    return _global_tool_search
