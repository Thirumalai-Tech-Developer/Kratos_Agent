from __future__ import annotations

from typing import Any, Dict, List, Optional


class BrowserSessionManager:
    """Single authoritative browser context facade around the existing manager."""

    def __init__(self) -> None:
        from kratos_agent.computer.browser.manager import get_browser_manager
        self._manager = get_browser_manager()

    def discover(self) -> Dict[str, Any]:
        target = getattr(self._manager, "active_target", None)
        return {
            "manager": type(self._manager).__name__,
            "active_target": getattr(target, "page_id", None),
            "locked": bool(getattr(target, "locked", False)) if target else False,
        }

    def open(self, url: str) -> Any:
        return self._manager.open_url(url)

    def reuse_or_open(self, url: str) -> Any:
        return self._manager.open_url(url)
