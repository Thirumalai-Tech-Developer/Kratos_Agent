"""Active computer browser target tracking and session persistence."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BrowserTarget:
    """Represents an active, addressable browser target."""
    browser_pid: int | None = None
    window_handle: int | None = None
    context_id: str | None = None
    page_id: str | None = None
    url: str | None = None
    title: str | None = None
    created_by_kratos: bool = False
    user_selected: bool = False
    last_verified: float | None = None
    browser_name: str = "chrome"
    foreground: bool = False

    def to_dict(self) -> dict[str, Any]:
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
class BrowserTaskContext:
    """Explicit browser task context tracking process, window, and locked tab ownership (§6)."""
    task_id: str = ""
    pid: int | None = None
    hwnd: int | None = None
    tab_id: str | None = None
    url: str | None = None
    title: str | None = None
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    locked: bool = False
    completed: bool = False
    page: object | None = None
    page_id: str | None = None
    initial_url: str | None = None
    window_handle: int | None = None
    browser_pid: int | None = None
    current_url: str | None = None

    def __post_init__(self) -> None:
        if self.window_handle is not None and self.hwnd is None:
            self.hwnd = self.window_handle
        elif self.hwnd is not None and self.window_handle is None:
            self.window_handle = self.hwnd

        if self.browser_pid is not None and self.pid is None:
            self.pid = self.browser_pid
        elif self.pid is not None and self.browser_pid is None:
            self.browser_pid = self.pid

        if self.current_url is not None and self.url is None:
            self.url = self.current_url
        elif self.url is not None and self.current_url is None:
            self.current_url = self.url

    def touch(self) -> None:
        self.last_activity = time.time()

    def is_closed(self) -> bool:
        if self.page is not None:
            if hasattr(self.page, "is_closed") and callable(self.page.is_closed):
                return bool(self.page.is_closed())
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "pid": self.pid,
            "hwnd": self.hwnd,
            "tab_id": self.tab_id,
            "url": self.url,
            "title": self.title,
            "created_at": self.created_at,
            "last_activity": self.last_activity,
            "locked": self.locked,
            "completed": self.completed,
            "page_id": self.page_id,
            "initial_url": self.initial_url,
            "window_handle": self.hwnd,
            "browser_pid": self.pid,
            "current_url": self.url,
        }


# Fully compatible alias
BrowserTaskTarget = BrowserTaskContext


class BrowserTaskError(Exception):
    """Base exception for browser task continuity."""


class BrowserTaskNotInitialized(BrowserTaskError):
    """Raised when an operation is attempted without an active browser task (§7)."""


class BrowserTaskPageMissing(BrowserTaskError):
    """Raised when the active browser task has no page assigned (§7)."""


class BrowserTaskPageUnlocked(BrowserTaskError):
    """Raised when the task page is not locked to the task (§7)."""


class BrowserTaskTabLost(BrowserTaskError):
    """Raised when the task tab is closed or lost during execution (§10)."""


class FocusError(BrowserTaskError):
    """Raised when Chrome window cannot be brought to foreground (§5)."""


class TabContinuityViolation(BrowserTaskError):
    """Raised when tab identity diverges during task execution (§15)."""


def log_browser_target(target: BrowserTarget | None) -> None:
    """Prints standard debug log block for browser target (§61)."""
    if target:
        print(f"[BROWSER TARGET]\nPID: {target.browser_pid}\nHWND: {target.window_handle}\nContext: {target.context_id}\nPage: {target.page_id}\nURL: {target.url}")
    else:
        print("[BROWSER TARGET]\nPID: None\nHWND: None\nContext: None\nPage: None\nURL: None")


def log_browser_task(target: BrowserTaskTarget | None) -> None:
    """Prints standard debug log block for browser task (§15)."""
    if target:
        print(f"[BROWSER TASK]\nTask ID: {target.task_id}\nWindow HWND: {target.window_handle}\nChrome PID: {target.browser_pid}\nTask Tab: {target.tab_id}\nLocked: {target.locked}")
    else:
        print("[BROWSER TASK]\nTask ID: None\nWindow HWND: None\nChrome PID: None\nTask Tab: None\nLocked: False")


class BrowserTargetManager:
    """Manages the active browser target across sequential user commands."""

    def __init__(self) -> None:
        self._active_target: BrowserTarget | None = None
        self._active_task_target: BrowserTaskTarget | None = None

    def get_active_target(self) -> BrowserTarget | None:
        return self._active_target

    def set_active_target(self, target: BrowserTarget) -> None:
        self._active_target = target
        log_browser_target(target)

    def get_active_task_target(self) -> BrowserTaskTarget | None:
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
        url: str | None = None,
        title: str | None = None,
        foreground: bool | None = None,
        window_handle: int | None = None,
        page_id: str | None = None,
        browser_pid: int | None = None,
        user_selected: bool | None = None,
        last_verified: float | None = None,
    ) -> BrowserTarget | None:
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

    def resolve_target(self) -> BrowserTarget | None:
        """Resolves existing target, verifying that process or window still exists if possible."""
        if not self._active_target:
            return None
        # Target still registered in working runtime state
        return self._active_target


_target_manager: BrowserTargetManager | None = None


def get_target_manager() -> BrowserTargetManager:
    global _target_manager
    if _target_manager is None:
        _target_manager = BrowserTargetManager()
    return _target_manager

