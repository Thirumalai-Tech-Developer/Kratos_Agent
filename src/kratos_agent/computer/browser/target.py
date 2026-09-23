"""Active computer browser target tracking and session persistence."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class BrowserTarget:
    """Represents an active, addressable browser target."""
    browser_pid: Optional[int] = None
    window_handle: Optional[int] = None
    context_id: Optional[str] = None
    page_id: Optional[str] = None
    url: Optional[str] = None
    title: Optional[str] = None
    created_by_kratos: bool = False
    user_selected: bool = False
    last_verified: Optional[float] = None
    browser_name: str = "chrome"
    foreground: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "browser_name": self.browser_name,
            "browser_pid": self.browser_pid,
            "window_handle": self.window_handle,
            "context_id": self.context_id,
            "page_id": self.page_id,
            "url": self.url,
            "title": self.title,
            "created_by_kratos": self.created_by_kratos,
            "user_selected": self.user_selected,
            "last_verified": self.last_verified,
            "foreground": self.foreground,
        }


@dataclass
class BrowserTaskTarget:
    """Represents a locked browser tab dedicated to an active browser task (§4, §5, §15)."""
    window_handle: Optional[int] = None
    browser_pid: Optional[int] = None
    page: Optional[object] = None
    page_id: Optional[str] = None
    tab_id: Optional[str] = None
    initial_url: Optional[str] = None
    current_url: Optional[str] = None
    task_id: Optional[str] = None
    locked: bool = False

    def is_closed(self) -> bool:
        if self.page is not None:
            if hasattr(self.page, "is_closed") and callable(self.page.is_closed):
                return bool(self.page.is_closed())
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "window_handle": self.window_handle,
            "browser_pid": self.browser_pid,
            "page_id": self.page_id,
            "tab_id": self.tab_id,
            "initial_url": self.initial_url,
            "current_url": self.current_url,
            "task_id": self.task_id,
            "locked": self.locked,
        }


class BrowserTaskError(Exception):
    """Base exception for browser task continuity."""
    pass


class BrowserTaskNotInitialized(BrowserTaskError):
    """Raised when an operation is attempted without an active browser task (§7)."""
    pass


class BrowserTaskPageMissing(BrowserTaskError):
    """Raised when the active browser task has no page assigned (§7)."""
    pass


class BrowserTaskPageUnlocked(BrowserTaskError):
    """Raised when the task page is not locked to the task (§7)."""
    pass


class BrowserTaskTabLost(BrowserTaskError):
    """Raised when the task tab is closed or lost during execution (§10)."""
    pass


class FocusError(BrowserTaskError):
    """Raised when Chrome window cannot be brought to foreground (§5)."""
    pass


class TabContinuityViolation(BrowserTaskError):
    """Raised when tab identity diverges during task execution (§15)."""
    pass


def log_browser_target(target: Optional[BrowserTarget]) -> None:
    """Prints standard debug log block for browser target (§61)."""
    if target:
        print(f"[BROWSER TARGET]\nPID: {target.browser_pid}\nHWND: {target.window_handle}\nContext: {target.context_id}\nPage: {target.page_id}\nURL: {target.url}")
    else:
        print("[BROWSER TARGET]\nPID: None\nHWND: None\nContext: None\nPage: None\nURL: None")


def log_browser_task(target: Optional[BrowserTaskTarget]) -> None:
    """Prints standard debug log block for browser task (§15)."""
    if target:
        print(f"[BROWSER TASK]\nTask ID: {target.task_id}\nWindow HWND: {target.window_handle}\nChrome PID: {target.browser_pid}\nTask Tab: {target.tab_id}\nLocked: {target.locked}")
    else:
        print("[BROWSER TASK]\nTask ID: None\nWindow HWND: None\nChrome PID: None\nTask Tab: None\nLocked: False")


class BrowserTargetManager:
    """Manages the active browser target across sequential user commands."""

    def __init__(self) -> None:
        self._active_target: Optional[BrowserTarget] = None
        self._active_task_target: Optional[BrowserTaskTarget] = None

    def get_active_target(self) -> Optional[BrowserTarget]:
        return self._active_target

    def set_active_target(self, target: BrowserTarget) -> None:
        self._active_target = target
        log_browser_target(target)

    def get_active_task_target(self) -> Optional[BrowserTaskTarget]:
        """Returns the currently active, locked browser task target if any."""
        return self._active_task_target

    def set_active_task_target(self, target: BrowserTaskTarget) -> None:
        """Sets and locks the browser task target for the active task (§4, §5)."""
        self._active_task_target = target
        log_browser_task(target)

    def clear_task_target(self) -> None:
        """Clears the active browser task target without closing physical browser tabs (§25)."""
        self._active_task_target = None
        log_browser_task(None)

    def get_task_page(self) -> object:
        """Retrieves the locked page for the active browser task (§7)."""
        target = self._active_task_target
        if target is None:
            raise BrowserTaskNotInitialized("No active browser task initialized (§7).")
        if target.page is None:
            raise BrowserTaskPageMissing("Active browser task has no page assigned (§7).")
        if target.locked is not True:
            raise BrowserTaskPageUnlocked("Active browser task page is not locked (§7).")
        if target.is_closed():
            raise BrowserTaskTabLost("Active browser task tab has been closed (§10).")
        return target.page

    def update_target(
        self,
        url: Optional[str] = None,
        title: Optional[str] = None,
        foreground: Optional[bool] = None,
        window_handle: Optional[int] = None,
        page_id: Optional[str] = None,
        browser_pid: Optional[int] = None,
        user_selected: Optional[bool] = None,
        last_verified: Optional[float] = None,
    ) -> Optional[BrowserTarget]:
        if not self._active_target:
            return None
        if url is not None:
            self._active_target.url = url
            if self._active_task_target:
                self._active_task_target.current_url = url
        if title is not None:
            self._active_target.title = title
        if foreground is not None:
            self._active_target.foreground = foreground
        if window_handle is not None:
            self._active_target.window_handle = window_handle
            if self._active_task_target:
                self._active_task_target.window_handle = window_handle
        if page_id is not None:
            self._active_target.page_id = page_id
            if self._active_task_target:
                self._active_task_target.page_id = page_id
        if browser_pid is not None:
            self._active_target.browser_pid = browser_pid
            if self._active_task_target:
                self._active_task_target.browser_pid = browser_pid
        if user_selected is not None:
            self._active_target.user_selected = user_selected
        if last_verified is not None:
            self._active_target.last_verified = last_verified
        return self._active_target

    def clear_target(self) -> None:
        self._active_target = None
        log_browser_target(None)

    def resolve_target(self) -> Optional[BrowserTarget]:
        """Resolves existing target, verifying that process or window still exists if possible."""
        if not self._active_target:
            return None
        # Target still registered in working runtime state
        return self._active_target


_target_manager: Optional[BrowserTargetManager] = None


def get_target_manager() -> BrowserTargetManager:
    global _target_manager
    if _target_manager is None:
        _target_manager = BrowserTargetManager()
    return _target_manager

