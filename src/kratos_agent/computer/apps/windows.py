"""Desktop window management using native OS APIs."""
from __future__ import annotations
import re
import sys
from typing import Any, Dict, List, Optional

from kratos_agent.computer.gui.models import WindowInfo, Rect
from kratos_agent.computer.state import ActionResult

try:
    import pygetwindow as gw
except ImportError:
    gw = None


def _activate_hwnd_win32(hwnd: int) -> bool:
    """Activates and brings a Win32 window to the foreground, bypassing focus locks (§6, §7)."""
    import ctypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        else:
            user32.ShowWindow(hwnd, 5)  # SW_SHOW

        fore_hwnd = user32.GetForegroundWindow()
        fore_thread = user32.GetWindowThreadProcessId(fore_hwnd, None)
        app_thread = kernel32.GetCurrentThreadId()

        if fore_thread != app_thread:
            user32.AttachThreadInput(fore_thread, app_thread, True)
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.AttachThreadInput(fore_thread, app_thread, False)
        else:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


class WindowManager:
    """Manages application windows (list, focus, move, resize, close)."""

    def list_windows(self, include_minimized: bool = True) -> List[WindowInfo]:
        """Lists open application windows with titles, bounds, and active state."""
        windows: List[WindowInfo] = []

        if sys.platform == "win32" and gw:
            try:
                for win in gw.getAllWindows():
                    if win.title:  # Only named windows
                        if not include_minimized and win.isMinimized:
                            continue
                        windows.append(WindowInfo(
                            id=str(win._hWnd),
                            title=win.title,
                            app_name=win.title,
                            is_active=bool(win.isActive),
                            bounds={"x": win.left, "y": win.top, "w": win.width, "h": win.height},
                        ))
            except Exception:
                pass
        elif sys.platform == "linux":
            import subprocess
            try:
                out = subprocess.check_output(["wmctrl", "-l", "-G"], text=True)
                for line in out.strip().split("\n"):
                    if not line:
                        continue
                    parts = line.split(maxsplit=7)
                    if len(parts) >= 8:
                        windows.append(WindowInfo(
                            id=parts[0],
                            title=parts[7],
                            app_name=parts[7],
                            is_active=False,
                            bounds={"x": int(parts[2]), "y": int(parts[3]), "w": int(parts[4]), "h": int(parts[5])},
                        ))
            except Exception:
                pass

        return windows

    def focus_window(self, handle: Optional[str] = None, title_regex: Optional[str] = None) -> ActionResult:
        """Brings a window to the foreground by handle or title regex (§6, §7)."""
        target_win = None

        if sys.platform == "win32":
            if handle and str(handle).isdigit():
                # Direct hwnd activation
                ok = _activate_hwnd_win32(int(handle))
                if ok:
                    return ActionResult(ok=True, action="window_focus", data={"handle": str(handle)})

            if gw:
                try:
                    all_wins = gw.getAllWindows()
                    if handle:
                        for w in all_wins:
                            if str(w._hWnd) == str(handle):
                                target_win = w
                                break
                    elif title_regex:
                        pat = re.compile(title_regex, re.IGNORECASE)
                        for w in all_wins:
                            if pat.search(w.title):
                                target_win = w
                                break

                    if target_win:
                        _activate_hwnd_win32(int(target_win._hWnd))
                        return ActionResult(ok=True, action="window_focus", data={"handle": str(target_win._hWnd), "title": target_win.title})
                except Exception as e:
                    return ActionResult(ok=False, action="window_focus", detail=str(e))

        elif sys.platform == "linux":
            import subprocess
            try:
                cmd = ["wmctrl", "-i", "-a", handle] if handle else ["wmctrl", "-a", title_regex or ""]
                subprocess.run(cmd, check=True)
                return ActionResult(ok=True, action="window_focus", data={"target": handle or title_regex})
            except Exception as e:
                return ActionResult(ok=False, action="window_focus", detail=str(e))

        return ActionResult(ok=False, action="window_focus", detail="Window not found")

    def window_action(self, handle: str, action: str = "restore", rect: Optional[Rect] = None) -> ActionResult:
        """Performs window action: 'minimize', 'maximize', 'restore', 'close', 'move_resize'."""
        if sys.platform == "win32" and gw:
            try:
                for w in gw.getAllWindows():
                    if str(w._hWnd) == str(handle):
                        if action == "minimize":
                            w.minimize()
                        elif action == "maximize":
                            w.maximize()
                        elif action == "restore":
                            w.restore()
                        elif action == "close":
                            w.close()
                        elif action == "move_resize" and rect:
                            w.moveTo(rect.x, rect.y)
                            w.resizeTo(rect.w, rect.h)
                        return ActionResult(ok=True, action=f"window_{action}", data={"handle": handle})
            except Exception as e:
                return ActionResult(ok=False, action=f"window_{action}", detail=str(e))

        elif sys.platform == "linux":
            import subprocess
            try:
                if action == "close":
                    subprocess.run(["wmctrl", "-i", "-c", handle], check=True)
                    return ActionResult(ok=True, action="window_close", data={"handle": handle})
            except Exception as e:
                return ActionResult(ok=False, action="window_close", detail=str(e))

        return ActionResult(ok=False, action=f"window_{action}", detail="Window handle not found")


_window_manager: Optional[WindowManager] = None


def get_window_manager() -> WindowManager:
    global _window_manager
    if _window_manager is None:
        _window_manager = WindowManager()
    return _window_manager
