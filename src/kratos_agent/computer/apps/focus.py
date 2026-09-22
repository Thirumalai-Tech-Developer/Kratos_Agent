"""Focus management and active window arbiter."""
from __future__ import annotations
import sys
from typing import Optional

from kratos_agent.computer.gui.models import WindowInfo
from kratos_agent.computer.apps.windows import get_window_manager

try:
    import pygetwindow as gw
except ImportError:
    gw = None


def get_active_window() -> Optional[WindowInfo]:
    """Returns the current foreground active window."""
    if sys.platform == "win32" and gw:
        try:
            win = gw.getActiveWindow()
            if win and win.title:
                return WindowInfo(
                    id=str(win._hWnd),
                    title=win.title,
                    app_name=win.title,
                    is_active=True,
                    bounds={"x": win.left, "y": win.top, "w": win.width, "h": win.height},
                )
        except Exception:
            pass

    windows = get_window_manager().list_windows()
    for w in windows:
        if w.is_active:
            return w
    return windows[0] if windows else None


def set_focus(target: str) -> bool:
    """Sets focus to a window by ID or title regex."""
    res = get_window_manager().focus_window(handle=target if target.isdigit() else None, title_regex=target if not target.isdigit() else None)
    return res.ok
