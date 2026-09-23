from __future__ import annotations

import asyncio
from typing import Any, Dict


class YouTubeExecutor:
    capability = "browser.youtube.play"

    async def execute(self, query: str) -> Dict[str, Any]:
        from kratos_agent.computer.browser.playwright import PlaywrightDriver, can_report_success
        result = await asyncio.get_running_loop().run_in_executor(None, PlaywrightDriver().search_and_play_youtube, query)
        return {
            "ok": bool(result.ok),
            "verified": bool(getattr(result, "verified", False) and can_report_success(result)),
            "query": query,
            "url": getattr(result, "url", ""),
            "detail": getattr(result, "detail", ""),
        }
