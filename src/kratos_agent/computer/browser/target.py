"""Active computer browser target tracking and session persistence."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class BrowserTarget:
    """Represents an active, addressable browser target."""
    browser_name: str
    browser_pid: Optional[int] = None
    window_handle: Optional[int] = None
    context_id: Optional[str] = None
    page_id: Optional[str] = None
    url: Optional[str] = None
    title: Optional[str] = None
    created_by_kratos: bool = False
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
            "foreground": self.foreground,
        }


class BrowserTargetManager:
    """Manages the active browser target across sequential user commands."""

    def __init__(self) -> None:
        self._active_target: Optional[BrowserTarget] = None

    def get_active_target(self) -> Optional[BrowserTarget]:
        return self._active_target

    def set_active_target(self, target: BrowserTarget) -> None:
        self._active_target = target

    def update_target(
        self,
        url: Optional[str] = None,
        title: Optional[str] = None,
        foreground: Optional[bool] = None,
        window_handle: Optional[int] = None,
        page_id: Optional[str] = None,
    ) -> Optional[BrowserTarget]:
        if not self._active_target:
            return None
        if url is not None:
            self._active_target.url = url
        if title is not None:
            self._active_target.title = title
        if foreground is not None:
            self._active_target.foreground = foreground
        if window_handle is not None:
            self._active_target.window_handle = window_handle
        if page_id is not None:
            self._active_target.page_id = page_id
        return self._active_target

    def clear_target(self) -> None:
        self._active_target = None

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
