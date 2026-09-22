"""Browser automation manager coordinating persistent sessions, window reuse, and CDP/Playwright (§1, §2, §3, §4, §5, §6, §7)."""
from __future__ import annotations

import os
import re
import sys
import time
import subprocess
from typing import Any, Dict, List, Optional

from kratos_agent.ccs.browser.cdp import cdp_client
from kratos_agent.computer.state import ActionResult
from kratos_agent.computer.apps.windows import get_window_manager
from kratos_agent.computer.apps.focus import focus_window, get_active_window
from kratos_agent.computer.apps.focus_policy import FocusPolicy
from kratos_agent.computer.browser.target import BrowserTarget, get_target_manager


class BrowserManager:
    """Single authority for browser lifecycle, window reuse, and persistent sessions."""

    MAX_CONTROLLED_CHROME_INSTANCES: int = 1

    def __init__(self) -> None:
        self._cdp = cdp_client
        self._target_mgr = get_target_manager()
        self._browser_pid: Optional[int] = None
        self._window_handle: Optional[int] = None

    def is_connected(self) -> bool:
        return self._cdp.is_available()

    def get_state(self) -> Dict[str, Any]:
        """Returns current browser URL, title, and connection status."""
        active_target = self._target_mgr.get_active_target()
        if self._cdp.is_available():
            try:
                url = self._cdp.evaluate("window.location.href")
                title = self._cdp.evaluate("document.title")
                if active_target:
                    self._target_mgr.update_target(url=url, title=title)
                return {
                    "connected": True,
                    "url": url,
                    "title": title,
                    "backend": "cdp",
                    "window_handle": active_target.window_handle if active_target else None,
                }
            except Exception:
                pass

        if active_target:
            return {
                "connected": False,
                "url": active_target.url,
                "title": active_target.title,
                "backend": "window_tracked",
                "window_handle": active_target.window_handle,
            }

        return {"connected": False, "url": None, "title": None, "backend": None}

    def find_existing_browser(self, browser: str = "chrome") -> Optional[Dict[str, Any]]:
        """Finds existing browser window, ranking active window > target handle > title match (§2, §5, §24)."""
        wm = get_window_manager()
        windows = wm.list_windows()

        # 1. Check active window first
        active = get_active_window()
        if active and any(b in active.title.lower() for b in (browser, "google chrome", "chrome", "edge")):
            handle = int(active.id) if active.id.isdigit() else None
            return {"handle": handle, "title": active.title, "is_active": True}

        # 2. Check active target handle
        target = self._target_mgr.get_active_target()
        if target and target.window_handle:
            for w in windows:
                if w.id == str(target.window_handle):
                    return {"handle": target.window_handle, "title": w.title, "is_active": w.is_active}

        # 3. Check for any Chrome / Edge window
        for w in windows:
            t_lower = w.title.lower()
            if any(b in t_lower for b in ("google chrome", "chrome", "edge")) or "youtube" in t_lower:
                handle = int(w.id) if w.id.isdigit() else None
                return {"handle": handle, "title": w.title, "is_active": w.is_active}

        return None

    def open_url(self, url: str, browser: str = "chrome", new_tab: bool = False) -> ActionResult:
        """Opens URL by reusing existing Chrome window and active tab by default (§2, §4, §5, §6, §7)."""
        if not re.match(r"^[a-zA-Z]+://", url):
            url = "https://" + url

        # 1. Check for existing browser window (§2, §24)
        existing = self.find_existing_browser(browser=browser)
        window_handle = existing["handle"] if existing else None

        # 2. If CDP is connected, navigate in existing tab
        if self._cdp.is_available():
            success = self._cdp.navigate(url)
            if window_handle:
                focus_window(window_handle, policy=FocusPolicy.FOCUS_TARGET)
            self._target_mgr.set_active_target(BrowserTarget(
                browser_name=browser,
                window_handle=window_handle,
                url=url,
                foreground=True,
                created_by_kratos=False,
            ))
            return ActionResult(
                ok=success,
                action="browser_open",
                detail=f"Navigated existing tab via CDP: {url}",
                data={"url": url, "method": "cdp_reuse", "window_handle": window_handle},
                verified=True,
            )

        # 3. If Chrome window is already open, reuse it and bring to foreground (§5, §6, §7)
        if existing and window_handle:
            focus_ok = focus_window(window_handle, policy=FocusPolicy.FOCUS_TARGET)
            # Reusing existing browser window — navigate via startfile or shortcut
            try:
                if sys.platform == "win32":
                    # Navigating via default handler attaches to existing session
                    os.startfile(url)
                    time.sleep(0.5)
                    focus_window(window_handle, policy=FocusPolicy.FOCUS_TARGET)
                else:
                    subprocess.Popen([browser, url], shell=False)
            except Exception as e:
                return ActionResult(ok=False, action="browser_open", detail=f"Failed to navigate existing browser: {e}")

            self._target_mgr.set_active_target(BrowserTarget(
                browser_name=browser,
                window_handle=window_handle,
                url=url,
                foreground=focus_ok,
                created_by_kratos=False,
            ))
            return ActionResult(
                ok=True,
                action="browser_open",
                detail=f"Reused existing Chrome window ({window_handle}) for {url}",
                data={"url": url, "method": "existing_window_reuse", "window_handle": window_handle, "foreground": focus_ok},
                verified=True,
            )

        # 4. Launch new browser process only if no existing window found (§2, §21, §22)
        try:
            launched_pid = None
            if sys.platform == "win32":
                try:
                    proc = subprocess.Popen([f"{browser}.exe", url], shell=False)
                    launched_pid = proc.pid
                except Exception:
                    os.startfile(url)
            else:
                proc = subprocess.Popen(["google-chrome" if browser == "chrome" else browser, url], shell=False)
                launched_pid = proc.pid

            time.sleep(1.0)
            new_win = self.find_existing_browser(browser=browser)
            new_handle = new_win["handle"] if new_win else None
            if new_handle:
                focus_window(new_handle, policy=FocusPolicy.FOCUS_TARGET)

            self._target_mgr.set_active_target(BrowserTarget(
                browser_name=browser,
                browser_pid=launched_pid,
                window_handle=new_handle,
                url=url,
                foreground=True,
                created_by_kratos=True,
            ))
            return ActionResult(
                ok=True,
                action="browser_open",
                detail=f"Launched browser with {url}",
                data={"url": url, "method": "os_launch", "window_handle": new_handle},
                verified=True,
            )
        except Exception as exc:
            return ActionResult(ok=False, action="browser_open", detail=f"Failed to open browser: {exc}")

    def navigate(self, action: str = "reload", url: Optional[str] = None) -> ActionResult:
        """Performs navigation: 'goto', 'reload', 'back', 'forward' on the active target (§4)."""
        target = self._target_mgr.get_active_target()
        if target and target.window_handle:
            focus_window(target.window_handle, policy=FocusPolicy.FOCUS_TARGET)

        if not self._cdp.is_available():
            if action == "goto" and url:
                return self.open_url(url)
            return ActionResult(ok=False, action="browser_navigate", detail="Browser not connected via CDP")

        if action == "goto" and url:
            success = self._cdp.navigate(url)
            if target:
                self._target_mgr.update_target(url=url)
            return ActionResult(ok=success, action="browser_navigate", data={"url": url}, verified=True)
        elif action == "reload":
            self._cdp.evaluate("window.location.reload()")
            return ActionResult(ok=True, action="browser_navigate", detail="Reloaded page", verified=True)
        elif action == "back":
            self._cdp.evaluate("window.history.back()")
            return ActionResult(ok=True, action="browser_navigate", detail="Navigated back", verified=True)
        elif action == "forward":
            self._cdp.evaluate("window.history.forward()")
            return ActionResult(ok=True, action="browser_navigate", detail="Navigated forward", verified=True)

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
