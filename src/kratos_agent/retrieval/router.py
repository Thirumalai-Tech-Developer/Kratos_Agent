"""Unified Retrieval Router spanning Web, Tools, Memory, Docs, and GitHub."""
from __future__ import annotations

import asyncio
import logging
import time

from kratos_agent.search import get_search_router
from kratos_agent.tools.discovery import get_tool_search

from .models import RetrievalQuery, RetrievalResult

logger = logging.getLogger(__name__)


class RetrievalRouter:
    """Unified retrieval authority for Master, Slave, and AgentLoop."""

    def __init__(self) -> None:
        self.search_router = get_search_router()
        self.tool_search = get_tool_search()

    async def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        """Dispatches unified query to requested target."""
        start_time = time.monotonic()
        target = query.target.lower().strip()
        text = query.text.strip()

        # 1. Target: WEB
        if target == "web":
            resp = await self.search_router.search(
                text,
                mode=query.mode,
                max_results=query.max_results,
            )
            latency = (time.monotonic() - start_time) * 1000
            return RetrievalResult(
                target="web",
                query=text,
                items=resp.results,
                total=resp.total_results,
                latency_ms=latency,
                metadata={"citations": resp.citations, "answer": resp.answer, "provider": resp.provider},
            )

        # 2. Target: TOOLS
        elif target == "tools":
            tools = self.tool_search.search(
                text,
                context=query.context,
                max_results=query.max_results,
            )
            latency = (time.monotonic() - start_time) * 1000
            return RetrievalResult(
                target="tools",
                query=text,
                items=tools,
                total=len(tools),
                latency_ms=latency,
            )

        # 3. Target: GITHUB
        elif target == "github":
            resp = await self.search_router.github.search(
                text,
                max_results=query.max_results,
            )
            latency = (time.monotonic() - start_time) * 1000
            return RetrievalResult(
                target="github",
                query=text,
                items=resp.results,
                total=resp.total_results,
                latency_ms=latency,
                metadata={"citations": resp.citations},
            )

        # 4. Target: MEMORY
        elif target == "memory":
            from kratos_agent.core.cognitive_memory import get_cognitive_memory
            mem = get_cognitive_memory()
            hits = mem.retrieve_context(text, max_tokens=1500)
            latency = (time.monotonic() - start_time) * 1000
            return RetrievalResult(
                target="memory",
                query=text,
                items=[{"content": hits}],
                total=1 if hits else 0,
                latency_ms=latency,
            )

        # 5. Target: ALL
        elif target == "all":
            web_task = self.search_router.search(text, mode=query.mode, max_results=query.max_results)
            tools_task = asyncio.to_thread(self.tool_search.search, text, query.context, query.max_results)
            web_resp, tools_list = await asyncio.gather(web_task, tools_task, return_exceptions=True)

            combined_items = []
            if not isinstance(web_resp, Exception):
                combined_items.extend(web_resp.results)
            if not isinstance(tools_list, Exception):
                combined_items.extend(tools_list)

            latency = (time.monotonic() - start_time) * 1000
            return RetrievalResult(
                target="all",
                query=text,
                items=combined_items,
                total=len(combined_items),
                latency_ms=latency,
            )

        # Fallback default: web search
        resp = await self.search_router.search(text, mode=query.mode, max_results=query.max_results)
        latency = (time.monotonic() - start_time) * 1000
        return RetrievalResult(
            target="web",
            query=text,
            items=resp.results,
            total=resp.total_results,
            latency_ms=latency,
        )


# Global RetrievalRouter singleton
_global_retrieval_router: RetrievalRouter | None = None


def get_retrieval_router() -> RetrievalRouter:
    global _global_retrieval_router
    if _global_retrieval_router is None:
        _global_retrieval_router = RetrievalRouter()
    return _global_retrieval_router
