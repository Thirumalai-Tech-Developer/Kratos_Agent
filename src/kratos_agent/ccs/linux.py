
import logging
logger = logging.getLogger(__name__)
import platform
import subprocess
from typing import Any

try:
    import psutil
    import pyautogui
    import pyperclip
except ImportError:
    pass

from .base import ComputerController, DisplayInfo, WindowInfo


class LinuxComputerController(ComputerController):
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
        
    def keyboard_press(self, keys: list[str]) -> None:
        pyautogui.hotkey(*keys)

    # ── SCREEN & VISION ────────────────────────────────────
    def take_screenshot(self, monitor_id: str | None = None) -> bytes:
        import io

        from PIL import ImageGrab
        img = ImageGrab.grab(all_screens=True)
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        return img_byte_arr.getvalue()
        
    def get_displays(self) -> list[DisplayInfo]:
        w, h = pyautogui.size()
        return [DisplayInfo(
            id="primary",
            is_primary=True,
            bounds={"x": 0, "y": 0, "width": w, "height": h},
            resolution=f"{w}x{h}"
        )]

    # ── WINDOW MANAGEMENT ──────────────────────────────────
    def list_windows(self) -> list[WindowInfo]:
        # Using wmctrl on Linux
        windows = []
        try:
            output = subprocess.check_output(['wmctrl', '-l'], text=True)
            for line in output.strip().split('\n'):
                if not line: continue
                parts = line.split(maxsplit=3)
                if len(parts) == 4:
                    win_id = parts[0]
                    title = parts[3]
                    windows.append(WindowInfo(
                        id=win_id,
                        title=title,
                        app_name=title,
                        is_active=False,
                        bounds={"x": 0, "y": 0, "width": 0, "height": 0}
                    ))
        except Exception as exc:
            logger.debug("Operation error suppressed: %s", exc)
        return windows
        
    def focus_window(self, window_id: str) -> bool:
        try:
            subprocess.run(['wmctrl', '-i', '-a', window_id], check=True)
            return True
        except Exception:
            return False
            
    def close_window(self, window_id: str) -> bool:
        try:
            subprocess.run(['wmctrl', '-i', '-c', window_id], check=True)
            return True
        except Exception:
            return False

    # ── CLIPBOARD ──────────────────────────────────────────
    def get_clipboard(self) -> str:
        return pyperclip.paste()
        
    def set_clipboard(self, text: str) -> None:
        pyperclip.copy(text)

    # ── SYSTEM CAPABILITIES ────────────────────────────────
    def get_system_info(self) -> dict[str, Any]:
        return {
            "os": "Linux",
            "release": platform.release(),
            "version": platform.version(),
            "architecture": platform.machine(),
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage('/').percent
        }
        
    def list_applications(self) -> list[dict[str, str]]:
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
        try:
            import shlex
            argv = shlex.split(app_name_or_path)
            subprocess.Popen(argv, shell=False)
            return True
        except Exception:
            return False
