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


def get_current_foreground_hwnd() -> Optional[int]:
    """Returns the actual physical foreground window HWND (§7)."""
    if sys.platform == "win32":
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            return int(hwnd) if hwnd else None
        except Exception:
            pass
    active = get_active_window()
    if active and str(active.id).isdigit():
        return int(active.id)
    return None


def recover_foreground(expected_hwnd: int | str) -> bool:
    """Attempts aggressive recovery of stolen focus to the expected window (§7)."""
    target_id = str(expected_hwnd)
    target_int = int(expected_hwnd) if target_id.isdigit() else None
    wm = get_window_manager()
    
    # 1. Standard focus call
    wm.focus_window(handle=target_id)
    actual_hwnd = get_current_foreground_hwnd()
    if target_int is not None and actual_hwnd == target_int:
        return True

    # 2. Win32 force restore/activate if minimized or behind
    if sys.platform == "win32" and target_int is not None:
        try:
            from kratos_agent.computer.apps.windows import _activate_hwnd_win32
            _activate_hwnd_win32(target_int)
            actual_hwnd = get_current_foreground_hwnd()
            if actual_hwnd == target_int:
                return True
        except Exception:
            pass

    return False


def ensure_task_window_foreground(
    expected_hwnd: int | str,
    max_retries: int = 3,
) -> bool:
    """Verifies that the expected window is actively foregrounded; recovers if focus was stolen (§7)."""
    target_id = str(expected_hwnd)
    target_int = int(expected_hwnd) if target_id.isdigit() else None
    if target_int is None:
        return True

    import time
    for attempt in range(1, max_retries + 1):
        actual_hwnd = get_current_foreground_hwnd()
        if actual_hwnd == target_int:
            print(f"[FOREGROUND]\nExpected HWND: {target_id}\nActual HWND: {actual_hwnd}\nFocused: True")
            return True

        # Focus stolen by Antigravity, terminal, or another app — recover
        print(f"[FOREGROUND_STEAL_DETECTED]\nExpected HWND: {target_id}\nActual HWND: {actual_hwnd}\nAttempting recovery ({attempt}/{max_retries})...")
        recovered = recover_foreground(target_int)
        actual_hwnd = get_current_foreground_hwnd()
        if recovered or (actual_hwnd == target_int):
            print(f"[FOREGROUND]\nExpected HWND: {target_id}\nActual HWND: {actual_hwnd}\nFocused: True")
            return True

        time.sleep(0.15 * attempt)

    actual_hwnd = get_current_foreground_hwnd()
    print(f"[FOREGROUND]\nExpected HWND: {target_id}\nActual HWND: {actual_hwnd}\nFocused: False")
    return False


def focus_window(
    window_handle: int | str,
    policy: FocusPolicy = FocusPolicy.FOCUS_TARGET,
) -> bool:
    """Brings a window to the foreground and verifies active focus with up to 3 bounded attempts (§7, §14, §16, §61)."""
    global _previous_foreground_handle
    if policy == FocusPolicy.KEEP_CURRENT:
        return True

    # Record previous foreground window for explicit tracking
    current_active = get_active_window()
    if current_active:
        _previous_foreground_handle = str(current_active.id)

    target_id = str(window_handle)
    wm = get_window_manager()
    wm.focus_window(handle=target_id)
    return ensure_task_window_foreground(target_id)


def restore_previous_window() -> bool:
    """Restores the window that had focus before the task only if explicitly requested (§15)."""
    global _previous_foreground_handle
    if _previous_foreground_handle:
        res = get_window_manager().focus_window(handle=_previous_foreground_handle)
        _previous_foreground_handle = None
        return res.ok
    return False

