import platform
from typing import Dict, Any, List, Optional
import time

try:
    import pyautogui
    import psutil
    import pygetwindow as gw
    import pyperclip
    from PIL import ImageGrab
    import io
except ImportError:
    pass

from .base import ComputerController, WindowInfo, DisplayInfo

class WindowsComputerController(ComputerController):
    def __init__(self):
        super().__init__()
        pyautogui.FAILSAFE = False

    # ── MOUSE ──────────────────────────────────────────────
    def mouse_move(self, x: int, y: int) -> None:
        pyautogui.moveTo(x, y)
        
    def mouse_click(self, button: str = "left", double: bool = False) -> None:
        if double:
            pyautogui.doubleClick(button=button)
        else:
            pyautogui.click(button=button)
        
    def mouse_drag(self, x: int, y: int) -> None:
        pyautogui.dragTo(x, y)
        
    def mouse_scroll(self, clicks: int) -> None:
        pyautogui.scroll(clicks)

    # ── KEYBOARD ───────────────────────────────────────────
    def keyboard_type(self, text: str) -> None:
        pyautogui.write(text, interval=0.01)
        
    def keyboard_press(self, keys: List[str]) -> None:
        pyautogui.hotkey(*keys)

    # ── SCREEN & VISION ────────────────────────────────────
    def take_screenshot(self, monitor_id: Optional[str] = None) -> bytes:
        # Pillow's ImageGrab works well for Windows
        img = ImageGrab.grab(all_screens=True)
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        return img_byte_arr.getvalue()
        
    def get_displays(self) -> List[DisplayInfo]:
        # Pillow does not easily give individual monitor bounds in a robust cross-platform way,
        # but pyautogui.size() gives primary screen size.
        # For multi-monitor, mss is better, but ImageGrab all_screens captures bounding box.
        w, h = pyautogui.size()
        return [DisplayInfo(
            id="primary",
            is_primary=True,
            bounds={"x": 0, "y": 0, "width": w, "height": h},
            resolution=f"{w}x{h}"
        )]

    # ── WINDOW MANAGEMENT ──────────────────────────────────
    def list_windows(self) -> List[WindowInfo]:
        windows = []
        for win in gw.getAllWindows():
            if win.title:  # Only windows with titles
                windows.append(WindowInfo(
                    id=str(win._hWnd),
                    title=win.title,
                    app_name=win.title,
                    is_active=win.isActive,
                    bounds={"x": win.left, "y": win.top, "width": win.width, "height": win.height}
                ))
        return windows
        
    get_windows = list_windows

    def focus_window(self, window_id: str) -> bool:
        try:
            for win in gw.getAllWindows():
                if str(win._hWnd) == window_id:
                    if not win.isActive:
                        win.activate()
                    return True
        except Exception:
            pass
        return False
        
    def close_window(self, window_id: str) -> bool:
        try:
            for win in gw.getAllWindows():
                if str(win._hWnd) == window_id:
                    win.close()
                    return True
        except Exception:
            pass
        return False

    # ── CLIPBOARD ──────────────────────────────────────────
    def get_clipboard(self) -> str:
        return pyperclip.paste()
        
    def set_clipboard(self, text: str) -> None:
        pyperclip.copy(text)

    # ── SYSTEM CAPABILITIES ────────────────────────────────
    def get_system_info(self) -> Dict[str, Any]:
        return {
            "os": "Windows",
            "release": platform.release(),
            "version": platform.version(),
            "architecture": platform.machine(),
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage('/').percent
        }
        
    def list_applications(self) -> List[Dict[str, str]]:
        # Simplified running process list with names
        apps = []
        seen = set()
        for p in psutil.process_iter(['pid', 'name']):
            try:
                name = p.info['name']
                if name and name not in seen:
                    seen.add(name)
                    apps.append({"id": str(p.info['pid']), "name": name})
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return apps
        
    def launch_application(self, app_name_or_path: str) -> bool:
        import subprocess
        import os
        try:
            # os.startfile is Windows specific and opens files or apps via shell
            os.startfile(app_name_or_path)
            return True
        except Exception:
            try:
                import shlex
                argv = shlex.split(app_name_or_path, posix=False)
                subprocess.Popen(argv, shell=False)
                return True
            except Exception:
                return False
