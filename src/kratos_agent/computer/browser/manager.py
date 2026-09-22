"""Browser automation manager coordinating CDP and Playwright sessions."""
from __future__ import annotations
import os
import re
import sys
import subprocess
from typing import Any, Dict, List, Optional

from kratos_agent.ccs.browser.cdp import cdp_client
from kratos_agent.computer.state import ActionResult


class BrowserManager:
    """Manages active browser instances, navigation, tabs, and protocol bridges."""

    def __init__(self) -> None:
        self._cdp = cdp_client
        self._playwright_driver: Optional[Any] = None

    def is_connected(self) -> bool:
        return self._cdp.is_available()

    def get_state(self) -> Dict[str, Any]:
        """Returns current browser URL, title, and connection status."""
        if self._cdp.is_available():
            try:
                url = self._cdp.evaluate("window.location.href")
                title = self._cdp.evaluate("document.title")
                return {
                    "connected": True,
                    "url": url,
                    "title": title,
                    "backend": "cdp",
                }
            except Exception:
                pass
        return {"connected": False, "url": None, "title": None, "backend": None}

    def open_url(self, url: str, browser: str = "chrome") -> ActionResult:
        """Opens a URL in Chrome/Edge/Firefox or attaches to existing instance."""
        if not re.match(r"^[a-zA-Z]+://", url):
            url = "https://" + url

        # 1. Try CDP navigate if already connected
        if self._cdp.is_available() and self._cdp.navigate(url):
            return ActionResult(ok=True, action="browser_open", detail=f"Navigated via CDP: {url}", data={"url": url, "method": "cdp"})

        # 2. Launch browser process
        try:
            if sys.platform == "win32":
                try:
                    os.startfile(url)
                except Exception:
                    subprocess.Popen([f"{browser}.exe", url], shell=False)
            else:
                subprocess.Popen(["google-chrome" if browser == "chrome" else browser, url], shell=False)
            return ActionResult(ok=True, action="browser_open", detail=f"Launched browser with {url}", data={"url": url, "method": "os_launch"})
        except Exception as exc:
            return ActionResult(ok=False, action="browser_open", detail=f"Failed to open browser: {exc}")

    def navigate(self, action: str = "reload", url: Optional[str] = None) -> ActionResult:
        """Performs navigation: 'goto', 'reload', 'back', 'forward'."""
        if not self._cdp.is_available():
            if action == "goto" and url:
                return self.open_url(url)
            return ActionResult(ok=False, action="browser_navigate", detail="Browser not connected via CDP")

        if action == "goto" and url:
            success = self._cdp.navigate(url)
            return ActionResult(ok=success, action="browser_navigate", data={"url": url})
        elif action == "reload":
            self._cdp.evaluate("window.location.reload()")
            return ActionResult(ok=True, action="browser_navigate", detail="Reloaded page")
        elif action == "back":
            self._cdp.evaluate("window.history.back()")
            return ActionResult(ok=True, action="browser_navigate", detail="Navigated back")
        elif action == "forward":
            self._cdp.evaluate("window.history.forward()")
            return ActionResult(ok=True, action="browser_navigate", detail="Navigated forward")

        return ActionResult(ok=False, action="browser_navigate", detail=f"Unknown action {action}")

    def read_content(self, mode: str = "markdown", selector: Optional[str] = None) -> str:
        """Extracts page text, HTML, or markdown."""
        if not self._cdp.is_available():
            return "(Browser not connected via CDP)"

        target = f"document.querySelector('{selector}')" if selector else "document.body"
        if mode == "html":
            val = self._cdp.evaluate(f"{target} ? {target}.outerHTML : ''")
        else:
            val = self._cdp.evaluate(f"{target} ? {target}.innerText : ''")
        return str(val) if val else "(Empty page)"

    def execute_js(self, script: str) -> Any:
        if not self._cdp.is_available():
            return {"error": "Browser not connected via CDP"}
        return self._cdp.evaluate(script)


_browser_manager: Optional[BrowserManager] = None


def get_browser_manager() -> BrowserManager:
    global _browser_manager
    if _browser_manager is None:
        _browser_manager = BrowserManager()
    return _browser_manager
