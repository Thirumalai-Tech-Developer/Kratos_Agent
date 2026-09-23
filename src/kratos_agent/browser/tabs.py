from __future__ import annotations

from typing import Any, List


def list_tabs() -> List[Any]:
    from kratos_agent.computer.browser.manager import get_browser_manager
    manager = get_browser_manager()
    tabs = getattr(manager, "tabs", None)
    return list(tabs or [])
