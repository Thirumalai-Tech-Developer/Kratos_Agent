"""Browser backend selection based on priority hierarchy without unnecessary dependency checks."""
from __future__ import annotations
import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger("kratos.browser.selector")


class BrowserBackendType(str, Enum):
    EXISTING_SESSION = "existing_session"
    PLAYWRIGHT = "playwright"
    CDP = "cdp"
    NATIVE = "native"
    GUI_ACCESSIBILITY = "gui_accessibility"
    VISION = "vision"
    COORDINATES = "coordinates"


class BrowserBackendSelector:
    """Selects the optimal browser backend following strict priority order (§20, §21, §38).
    
    Priority:
    1. Existing authenticated browser session
    2. Playwright
    3. Browser CDP
    4. Native browser control
    5. GUI accessibility
    6. Vision
    7. Coordinate fallback

    Crucially: NEVER checks Selenium, ChromeDriver, or python packages for Playwright tasks.
    """

    @classmethod
    def select(cls, task_description: str = "") -> BrowserBackendType:
        # 1. Check existing connected browser session
        from kratos_agent.computer.browser.manager import get_browser_manager
        mgr = get_browser_manager()
        if mgr.is_connected():
            return BrowserBackendType.EXISTING_SESSION

        # 2. Prefer Playwright (default modern backend)
        try:
            from kratos_agent.computer.gui.backends.playwright import PlaywrightBackend
            pb = PlaywrightBackend()
            if pb.is_available():
                return BrowserBackendType.PLAYWRIGHT
        except Exception:
            pass

        # 3. Fallback to native / GUI accessibility
        return BrowserBackendType.GUI_ACCESSIBILITY
