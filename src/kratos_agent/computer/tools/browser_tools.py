"""Browser-specific computer tools."""
from __future__ import annotations
import json
from typing import Any, Dict, Optional

from kratos_agent.computer.browser.manager import get_browser_manager
from kratos_agent.computer.browser.playwright import PlaywrightDriver


def computer_browser_navigate(url: Optional[str] = None, action: str = "goto") -> str:
    """Navigates the browser: goto URL, reload, back, or forward."""
    bm = get_browser_manager()
    res = bm.navigate(action=action, url=url)
    return json.dumps(res.to_dict(), indent=2)


def computer_browser_read(selector: Optional[str] = None, mode: str = "text") -> str:
    """Reads visible text or HTML content from the browser page."""
    bm = get_browser_manager()
    return bm.read_content(mode=mode, selector=selector)


def computer_browser_click(selector: Optional[str] = None, role: Optional[str] = None, name: Optional[str] = None) -> str:
    """Clicks a web element semantically by role/name or CSS selector."""
    drv = PlaywrightDriver()
    res = drv.click(role=role, name=name, selector=selector)
    return json.dumps(res.to_dict(), indent=2)


def computer_browser_type(text: str, selector: Optional[str] = None, role: Optional[str] = None, name: Optional[str] = None) -> str:
    """Types text into an input or textarea on the active web page."""
    drv = PlaywrightDriver()
    res = drv.fill(text=text, role=role, name=name, selector=selector)
    return json.dumps(res.to_dict(), indent=2)
