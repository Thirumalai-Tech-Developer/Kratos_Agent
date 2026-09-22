"""Focus management and active window arbiter."""
from __future__ import annotations
import sys
from typing import Optional

from kratos_agent.computer.gui.models import WindowInfo
from kratos_agent.computer.apps.windows import get_window_manager

from kratos_agent.computer.apps.focus_policy import FocusPolicy

try:
    import pygetwindow as gw
except ImportError:
    gw = None

_previous_foreground_handle: Optional[str] = None


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


def focus_window(
    window_handle: int | str,
    policy: FocusPolicy = FocusPolicy.FOCUS_TARGET,
) -> bool:
    """Brings a window to the foreground and verifies active focus (§6, §7, §8)."""
    global _previous_foreground_handle
    if policy == FocusPolicy.KEEP_CURRENT:
        return True

    # Record previous foreground window
    current_active = get_active_window()
    if current_active:
        _previous_foreground_handle = str(current_active.id)

    target_id = str(window_handle)
    wm = get_window_manager()
    res = wm.focus_window(handle=target_id)
    if not res.ok:
        return False

    # Verify foreground window
    active = get_active_window()
    if active and str(active.id) == target_id:
        return True

    # Retry once after short yield (§7)
    import time
    time.sleep(0.1)
    wm.focus_window(handle=target_id)
    active = get_active_window()
    return bool(active and str(active.id) == target_id)


def restore_previous_window() -> bool:
    """Restores the window that had focus before the task (§26)."""
    global _previous_foreground_handle
    if _previous_foreground_handle:
        res = get_window_manager().focus_window(handle=_previous_foreground_handle)
        _previous_foreground_handle = None
        return res.ok
    return False
