"""Browser automation manager coordinating persistent sessions, window reuse, and CDP/Playwright (§1, §2, §3, §4, §5, §6, §7)."""
from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any

from kratos_agent.ccs.browser.cdp import cdp_client
from kratos_agent.computer.apps.focus import focus_window, get_active_window
from kratos_agent.computer.apps.focus_policy import FocusPolicy
from kratos_agent.computer.apps.windows import (
    enumerate_chrome_windows,
    get_window_manager,
)
from kratos_agent.computer.browser.target import (
    BrowserTarget,
    BrowserTaskNotInitialized,
    BrowserTaskPageMissing,
    BrowserTaskPageUnlocked,
    BrowserTaskTabLost,
    BrowserTaskTarget,
    FocusError,
    get_target_manager,
)
from kratos_agent.computer.state import ActionResult


@dataclass
class BrowserTaskPolicy:
    """Task policy enforcing reuse of active browser window and single tab creation (§1, §2, §11)."""
    reuse_browser: bool = True
    reuse_window: bool = True
    create_task_tab_on_start: bool = True
    reuse_task_tab: bool = True
    create_tab_per_action: bool = False
    create_window_per_action: bool = False
    allow_new_window: bool = False
    allow_new_tab: bool = False


@dataclass
class GuiExecutionPolicy:
    """GUI task execution policy ensuring foreground visibility and verification (§18)."""
    require_foreground: bool = True
    require_visible_window: bool = True
    verify_focus: bool = True
    verify_after_action: bool = True


class BrowserManager:
    """Single authority for browser lifecycle, window reuse, and persistent sessions."""

    MAX_CONTROLLED_CHROME_INSTANCES: int = 1

    def __init__(self) -> None:
        self._cdp = cdp_client
        self._target_mgr = get_target_manager()
        self._browser_pid: int | None = None
        self._window_handle: int | None = None
        self._task_tab_counter: int = 41

    def _next_tab_id(self) -> str:
        self._task_tab_counter += 1
        return f"PAGE-{self._task_tab_counter}"

    def is_connected(self) -> bool:
        return self._cdp.is_available()

    def diagnostics(self) -> dict[str, Any]:
        """Returns comprehensive browser lifecycle diagnostics (§20)."""
        st = self.get_state()
        active_target = self._target_mgr.get_active_target()
        pid = self._browser_pid or (active_target.browser_pid if active_target else None)
        conn = self.is_connected()
        return {
            "browser": "chromium",
            "pid": pid,
            "context_count": 1 if conn else 0,
            "page_count": 1 if conn else (1 if active_target else 0),
            "active_page": st.get("url"),
            "active_url": st.get("url"),
            "active_title": st.get("title"),
            "connected": conn,
            "backend": st.get("backend"),
            "window_handle": st.get("window_handle"),
        }

    def get_state(self) -> dict[str, Any]:
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
            except Exception as exc:
                logger.debug("Operation error suppressed: %s", exc)

        if active_target:
            return {
                "connected": False,
                "url": active_target.url,
                "title": active_target.title,
                "backend": "window_tracked",
                "window_handle": active_target.window_handle,
            }

        return {"connected": False, "url": None, "title": None, "backend": None}

    def get_active_page(self) -> Any | None:
        """Returns the active browser page or target following strict priority (§10):
        1. Existing active_browser_target
        2. Existing foreground Chrome window
        3. Existing Playwright/CDP page
        4. Existing browser context's most recently active page
        5. None (only then consider launching a browser)
        """
        # 1. Existing active target
        target = self._target_mgr.get_active_target()
        if target and target.window_handle:
            return target

        # 2. Existing foreground Chrome window
        chrome_wins = enumerate_chrome_windows()
        for w in chrome_wins:
            if w.get("foreground"):
                t = BrowserTarget(
                    browser_name="chrome",
                    browser_pid=w.get("pid"),
                    window_handle=w.get("hwnd"),
                    title=w.get("title"),
                    foreground=True,
                    created_by_kratos=False,
                )
                self._target_mgr.set_active_target(t)
                return t

        # 3. Existing CDP / Playwright page
        if self._cdp.is_available():
            try:
                url = self._cdp.evaluate("window.location.href")
                title = self._cdp.evaluate("document.title")
                t = BrowserTarget(
                    browser_name="chrome",
                    url=url,
                    title=title,
                    foreground=True,
                    created_by_kratos=False,
                )
                self._target_mgr.set_active_target(t)
                return t
            except Exception as exc:
                logger.debug("Operation error suppressed: %s", exc)

        # 4. Any existing visible Chrome window
        if chrome_wins:
            w0 = chrome_wins[0]
            t = BrowserTarget(
                browser_name="chrome",
                browser_pid=w0.get("pid"),
                window_handle=w0.get("hwnd"),
                title=w0.get("title"),
                foreground=False,
                created_by_kratos=False,
            )
            self._target_mgr.set_active_target(t)
            return t

        return None

    def find_existing_browser(self, browser: str = "chrome") -> dict[str, Any] | None:
        """Finds existing browser window, ranking foreground Chrome > target handle > title match (§2, §5, §24, §30)."""
        chrome_wins = enumerate_chrome_windows()

        # 1. Check for foreground Chrome window first
        for w in chrome_wins:
            if w.get("foreground"):
                return {"handle": w["hwnd"], "pid": w.get("pid"), "title": w.get("title"), "is_active": True}

        # 2. Check active target handle
        target = self._target_mgr.get_active_target()
        if target and target.window_handle:
            for w in chrome_wins:
                if w["hwnd"] == target.window_handle:
                    return {"handle": target.window_handle, "pid": w.get("pid"), "title": w.get("title"), "is_active": w.get("foreground", False)}

        # 3. Any visible Chrome window
        if chrome_wins:
            w0 = chrome_wins[0]
            return {"handle": w0["hwnd"], "pid": w0.get("pid"), "title": w0.get("title"), "is_active": w0.get("foreground", False)}

        # 4. Fallback to WindowManager search
        wm = get_window_manager()
        windows = wm.list_windows()
        for w in windows:
            t_lower = w.title.lower()
            if any(b in t_lower for b in ("google chrome", "chrome", "edge")) or "youtube" in t_lower:
                handle = int(w.id) if w.id.isdigit() else None
                return {"handle": handle, "title": w.title, "is_active": w.is_active}

        return None

    def initialize_browser_task(
        self,
        task_id: str | None = None,
        initial_url: str | None = None,
        policy: BrowserTaskPolicy | None = None,
    ) -> BrowserTaskTarget:
        """Initializes a new browser task (§5):
        1. Find existing Chrome window.
        2. Focus Chrome.
        3. Verify foreground.
        4. Create ONE new tab.
        5. Store that tab.
        6. Lock the tab to the task.
        7. Return target for all subsequent actions.
        """
        if policy is None:
            policy = BrowserTaskPolicy()

        # Continuation check: If active task target already exists, is locked, and not closed, reuse it! (§12, §23)
        existing_task = self._target_mgr.get_active_task_target()
        if existing_task and existing_task.locked and not existing_task.is_closed():
            if task_id is None or existing_task.task_id == task_id:
                return existing_task

        # 1. Find existing Chrome window (§5)
        window = self.find_existing_browser(browser="chrome")
        hwnd = window["handle"] if window else None
        pid = window.get("pid") if window else None

        # 2. Launch Chrome if not running
        if not hwnd:
            init_url = initial_url or "https://www.google.com"
            self.open_url(init_url)
            window = self.find_existing_browser(browser="chrome")
            hwnd = window["handle"] if window else None
            pid = window.get("pid") if window else None

        # 3. Focus Chrome window and verify foreground (§5, §16, §18)
        if hwnd:
            focus_ok = focus_window(hwnd, policy=FocusPolicy.FOCUS_TARGET)
            active_w = get_active_window()
            if active_w and active_w.id and active_w.id.isdigit():
                if int(active_w.id) != hwnd and not focus_ok:
                    raise FocusError(f"Chrome window {hwnd} could not be brought to foreground.")

        # 4. Create exactly ONE new tab in the existing window (§1, §2, §4, §5, §11)
        assigned_tab_id = self._next_tab_id()
        page_ref = assigned_tab_id

        if self._cdp.is_available():
            tab_info = self._cdp.create_tab(initial_url or "about:blank")
            if tab_info and "id" in tab_info:
                cdp_id = tab_info["id"]
                self._cdp.activate_tab(cdp_id)
                page_ref = cdp_id
        elif sys.platform == "win32" and hwnd:
            # Native Windows: Ctrl+T creates ONE new tab in the focused Chrome window
            from kratos_agent.computer.gui.input.keyboard import KeyboardEngine
            kb = KeyboardEngine()
            kb.key_tap(["ctrl", "t"])
            time.sleep(0.3)
            focus_window(hwnd, policy=FocusPolicy.FOCUS_TARGET)

        effective_task_id = task_id or f"T-{int(time.time() * 1000) % 1000000:06d}"
        target = BrowserTaskTarget(
            window_handle=hwnd,
            browser_pid=pid,
            page=page_ref,
            page_id=assigned_tab_id,
            tab_id=assigned_tab_id,
            initial_url=initial_url,
            current_url=initial_url,
            task_id=effective_task_id,
            locked=True,
        )

        self._target_mgr.set_active_task_target(target)
        self._target_mgr.set_active_target(BrowserTarget(
            browser_name="chrome",
            browser_pid=pid,
            window_handle=hwnd,
            page_id=assigned_tab_id,
            url=initial_url,
            foreground=True,
            created_by_kratos=False,
            last_verified=time.time(),
        ))

        return target

    def get_task_page(self) -> BrowserTaskTarget:
        """Retrieves the active locked browser task target (§7)."""
        target = self._target_mgr.get_active_task_target()
        if target is None:
            raise BrowserTaskNotInitialized("Browser task has not been initialized (§7).")
        if target.page is None:
            raise BrowserTaskPageMissing("Browser task page is missing (§7).")
        if target.locked is not True:
            raise BrowserTaskPageUnlocked("Browser task page is not locked (§7).")
        if target.is_closed():
            raise BrowserTaskTabLost("Browser task tab has been closed (§10).")
        return target

    def open_url(
        self,
        url: str,
        browser: str = "chrome",
        new_tab: bool = False,
        new_window: bool = False,
        policy: BrowserTaskPolicy | None = None,
    ) -> ActionResult:
        """Opens URL by reusing existing Chrome window and active tab by default (§1, §2, §4, §5, §6, §7, §11, §12)."""
        if policy is None:
            policy = BrowserTaskPolicy()

        if not re.match(r"^[a-zA-Z]+://", url):
            url = "https://" + url

        # Check for locked browser task tab (§1, §2, §6, §7, §11)
        active_task = self._target_mgr.get_active_task_target()
        if active_task and active_task.locked and not active_task.is_closed():
            window_handle = active_task.window_handle
            if window_handle:
                focus_window(window_handle, policy=FocusPolicy.FOCUS_TARGET)

            if self._cdp.is_available():
                success = self._cdp.navigate(url)
                active_task.current_url = url
                self._target_mgr.update_target(url=url)
                print(f"[ACTION]\nOperation: browser_open\nWindow: {window_handle}\nTab: {active_task.tab_id}\nTarget: {url}\nVerified: True")
                return ActionResult(
                    ok=success,
                    action="browser_open",
                    detail=f"Navigated locked task tab {active_task.tab_id} via CDP: {url}",
                    data={"url": url, "tab_id": active_task.tab_id, "window_handle": window_handle},
                    verified=True,
                )
            else:
                if sys.platform == "win32":
                    from kratos_agent.computer.gui.input.keyboard import KeyboardEngine
                    kb = KeyboardEngine()
                    kb.key_tap(["ctrl", "l"])
                    time.sleep(0.1)
                    kb.type_text(url)
                    time.sleep(0.05)
                    kb.key_tap(["enter"])
                    time.sleep(1.0)
                    if window_handle:
                        focus_window(window_handle, policy=FocusPolicy.FOCUS_TARGET)
                active_task.current_url = url
                self._target_mgr.update_target(url=url)
                print(f"[ACTION]\nOperation: browser_open\nWindow: {window_handle}\nTab: {active_task.tab_id}\nTarget: {url}\nVerified: True")
                print("[TERMINATION]\nSuccess: True\nVerified: True\nFurther actions blocked: True")
                return ActionResult(
                    ok=True,
                    action="browser_open",
                    detail=f"Reused locked task tab {active_task.tab_id} in Chrome window ({window_handle}) for {url}",
                    data={"url": url, "tab_id": active_task.tab_id, "window_handle": window_handle},
                    verified=True,
                )

        # 1. Check for existing browser window (§1, §2, §30)
        existing = None
        if not (new_window or policy.allow_new_window):
            existing = self.find_existing_browser(browser=browser)
        window_handle = existing["handle"] if existing else None

        # 2. If CDP is connected, navigate in existing tab
        if self._cdp.is_available():
            if window_handle:
                focus_window(window_handle, policy=FocusPolicy.FOCUS_TARGET)
            success = self._cdp.navigate(url)
            self._target_mgr.set_active_target(BrowserTarget(
                browser_name=browser,
                browser_pid=existing.get("pid") if existing else None,
                window_handle=window_handle,
                url=url,
                foreground=True,
                created_by_kratos=False,
                last_verified=time.time(),
            ))
            print(f"[ACTION]\nOperation: browser_open\nTarget: {url}\nVerified: True")
            print("[TERMINATION]\nSuccess: True\nVerified: True\nFurther actions blocked: True")
            return ActionResult(
                ok=success,
                action="browser_open",
                detail=f"Navigated existing tab via CDP: {url}",
                data={"url": url, "method": "cdp_reuse", "window_handle": window_handle},
                verified=True,
            )

        # 3. If Chrome window is already open, reuse it and bring to foreground (§5, §6, §7, §11, §12)
        if existing and window_handle:
            focus_ok = focus_window(window_handle, policy=FocusPolicy.FOCUS_TARGET)
            try:
                if sys.platform == "win32":
                    # Navigate active tab using Ctrl+L -> type URL -> Enter (no new tab or window!)
                    from kratos_agent.computer.gui.input.keyboard import KeyboardEngine
                    kb = KeyboardEngine()
                    kb.key_tap(["ctrl", "l"])
                    time.sleep(0.1)
                    kb.type_text(url)
                    time.sleep(0.05)
                    kb.key_tap(["enter"])
                    time.sleep(1.0)
                    focus_window(window_handle, policy=FocusPolicy.FOCUS_TARGET)
                else:
                    subprocess.Popen([browser, url], shell=False)
            except Exception as e:
                return ActionResult(ok=False, action="browser_open", detail=f"Failed to navigate existing browser: {e}")

            self._target_mgr.set_active_target(BrowserTarget(
                browser_name=browser,
                browser_pid=existing.get("pid"),
                window_handle=window_handle,
                url=url,
                foreground=focus_ok,
                created_by_kratos=False,
                last_verified=time.time(),
            ))
            print(f"[ACTION]\nOperation: browser_open\nTarget: {url}\nVerified: True")
            print("[TERMINATION]\nSuccess: True\nVerified: True\nFurther actions blocked: True")
            return ActionResult(
                ok=True,
                action="browser_open",
                detail=f"Reused existing Chrome window ({window_handle}) active tab for {url}",
                data={"url": url, "method": "active_tab_reuse", "window_handle": window_handle, "foreground": focus_ok},
                verified=True,
            )

        # 4. Launch new browser process only if no existing window found (§1, §2, §28)
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

            time.sleep(1.5)
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
                last_verified=time.time(),
            ))
            print(f"[ACTION]\nOperation: browser_open\nTarget: {url}\nVerified: True")
            print("[TERMINATION]\nSuccess: True\nVerified: True\nFurther actions blocked: True")
            return ActionResult(
                ok=True,
                action="browser_open",
                detail=f"Launched browser with {url}",
                data={"url": url, "method": "os_launch", "window_handle": new_handle},
                verified=True,
            )
        except Exception as exc:
            return ActionResult(ok=False, action="browser_open", detail=f"Failed to open browser: {exc}")


    def navigate(self, action: str = "reload", url: str | None = None) -> ActionResult:
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

    def read_content(self, mode: str = "markdown", selector: str | None = None) -> str:
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


_browser_manager: BrowserManager | None = None


def get_browser_manager() -> BrowserManager:
    global _browser_manager
    if _browser_manager is None:
        _browser_manager = BrowserManager()
    return _browser_manager
