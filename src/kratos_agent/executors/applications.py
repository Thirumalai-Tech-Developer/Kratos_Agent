from __future__ import annotations

import asyncio
from typing import Any


class ApplicationExecutor:
    async def launch(self, app_name: str) -> dict[str, Any]:
        from kratos_agent.computer.apps.launcher import get_launcher
        result = await asyncio.get_running_loop().run_in_executor(None, get_launcher().launch_and_verify, app_name)
        return {
            "ok": bool(result.ok),
            "verified": bool(getattr(result, "verified", False)),
            "app": app_name,
            "observation": getattr(result, "observation", ""),
            "detail": getattr(result, "detail", ""),
        }
