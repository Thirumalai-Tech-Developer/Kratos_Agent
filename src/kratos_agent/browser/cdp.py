from __future__ import annotations

from typing import Any, Dict


def cdp_health() -> Dict[str, Any]:
    try:
        from kratos_agent.computer.browser.manager import get_browser_manager
        manager = get_browser_manager()
        return {"available": True, "manager": type(manager).__name__}
    except Exception as exc:
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}
