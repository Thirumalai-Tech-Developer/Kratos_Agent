from __future__ import annotations

import asyncio
from typing import Any, Dict


class BrowserExecutor:
    async def navigate(self, url: str) -> Dict[str, Any]:
        from kratos_agent.computer.browser.manager import get_browser_manager
        result = await asyncio.get_running_loop().run_in_executor(None, get_browser_manager().open_url, url)
        return {"ok": result.ok, "verified": bool(getattr(result, "verified", result.ok)), "url": url, "detail": result.detail}
