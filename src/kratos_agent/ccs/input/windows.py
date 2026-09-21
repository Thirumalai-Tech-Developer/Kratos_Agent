import ctypes
import ctypes.wintypes as wintypes
import time
import random
from typing import List, Dict, Any, Optional

from kratos_agent.ccs.base import CapabilityUnavailable, Point, Rect, ActionResult
from kratos_agent.ccs.input.keys import get_vk_and_scancode

# ── ctypes setups ────────────────────────────────────────────────────────
user32 = ctypes.windll.user32

class MOUSEINPUT(ctypes.Structure):
    _fields_ = (("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)))

class KEYBDINPUT(ctypes.Structure):
    _fields_ = (("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)))

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = (("uMsg", wintypes.DWORD),
                ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD))

class INPUT_union(ctypes.Union):
    _fields_ = (("mi", MOUSEINPUT),
                ("ki", KEYBDINPUT),
                ("hi", HARDWAREINPUT))

class INPUT(ctypes.Structure):
    _fields_ = (("type", wintypes.DWORD),
                ("union", INPUT_union))

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
INPUT_HARDWARE = 2

# Mouse flags
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

# Keyboard flags
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

CLICK_HOLD_S = 0.025
PASTE_HOLD_S = 0.05

class WindowsInputEngine:
    def __init__(self, humanize: bool = False):
        self.humanize = humanize

    def _send_inputs(self, inputs: List[INPUT]) -> None:
        nInputs = len(inputs)
        pInputs = (INPUT * nInputs)(*inputs)
        cbSize = ctypes.sizeof(INPUT)
        user32.SendInput(nInputs, pInputs, cbSize)

    def _sleep(self, base_ms: int, jitter_pct: float = 0.2) -> None:
        if not self.humanize or base_ms == 0:
            return
        jitter = int(base_ms * jitter_pct)
        sleep_ms = random.randint(base_ms - jitter, base_ms + jitter)
        if sleep_ms > 0:
            time.sleep(sleep_ms / 1000.0)

    # ── MOUSE ────────────────────────────────────────────────────────────────
    def mouse_move(self, p: Point, duration_ms: int = 0, style: str = "instant") -> ActionResult:
        try:
            vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
            vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
            vw = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
            vh = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)

            if vw == 0 or vh == 0:
                return ActionResult(False, "mouse_move", "Virtual screen dimensions are zero")

            # Calculate normalized absolute coordinates
            nx = int(((p.x - vx) * 65535) / vw)
            ny = int(((p.y - vy) * 65535) / vh)

            inp = INPUT(type=INPUT_MOUSE, union=INPUT_union(mi=MOUSEINPUT(
                dx=nx, dy=ny, mouseData=0, 
                dwFlags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, 
                time=0, dwExtraInfo=None
            )))

            if style == "smooth" and duration_ms > 0 and self.humanize:
                # Cap total travel at 250 ms
                actual_duration = min(duration_ms, 250)
                steps = max(8, min(48, actual_duration // 12))
                for _ in range(steps):
                    self._send_inputs([inp])
                    time.sleep(actual_duration / steps / 1000.0)
            else:
                self._send_inputs([inp])
            
            return ActionResult(True, "mouse_move")
        except Exception as e:
            return ActionResult(False, "mouse_move", str(e))

    def mouse_click(self, p: Point | None = None, button: str = "left",
                    clicks: int = 1, modifiers: List[str] = [], style: str = "instant") -> ActionResult:
        try:
            if p:
                self.mouse_move(p, style=style)

            down_flag, up_flag = {
                "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
                "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
                "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
            }.get(button.lower(), (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP))

            # Modifier down
            mod_inputs = []
            for mod in modifiers:
                vk, sc, ext = get_vk_and_scancode(mod)
                flags = KEYEVENTF_SCANCODE | (KEYEVENTF_EXTENDEDKEY if ext else 0)
                mod_inputs.append(INPUT(type=INPUT_KEYBOARD, union=INPUT_union(ki=KEYBDINPUT(wVk=0, wScan=sc, dwFlags=flags, time=0, dwExtraInfo=None))))
            if mod_inputs:
                self._send_inputs(mod_inputs)

            for i in range(clicks):
                inp_down = INPUT(type=INPUT_MOUSE, union=INPUT_union(mi=MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=down_flag, time=0, dwExtraInfo=None)))
                inp_up = INPUT(type=INPUT_MOUSE, union=INPUT_union(mi=MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=up_flag, time=0, dwExtraInfo=None)))
                self._send_inputs([inp_down])
                time.sleep(CLICK_HOLD_S)  # 25 ms hold
                self._send_inputs([inp_up])
                if i < clicks - 1:
                    time.sleep(CLICK_HOLD_S)

            # Modifier up
            if mod_inputs:
                mod_up = []
                for mod in reversed(modifiers):
                    vk, sc, ext = get_vk_and_scancode(mod)
                    flags = KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP | (KEYEVENTF_EXTENDEDKEY if ext else 0)
                    mod_up.append(INPUT(type=INPUT_KEYBOARD, union=INPUT_union(ki=KEYBDINPUT(wVk=0, wScan=sc, dwFlags=flags, time=0, dwExtraInfo=None))))
                self._send_inputs(mod_up)

            return ActionResult(True, "mouse_click")
        except Exception as e:
            return ActionResult(False, "mouse_click", str(e))

    def mouse_drag(self, a: Point, b: Point, button: str = "left",
                   duration_ms: int = 200, steps: int = 24) -> ActionResult:
        # Move to A, button down, Move to B, button up
        try:
            self.mouse_move(a, style="instant")
            down_flag = MOUSEEVENTF_LEFTDOWN if button == "left" else MOUSEEVENTF_RIGHTDOWN
            self._send_inputs([INPUT(type=INPUT_MOUSE, union=INPUT_union(mi=MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=down_flag, time=0, dwExtraInfo=None)))])
            time.sleep(CLICK_HOLD_S)
            self.mouse_move(b, duration_ms=duration_ms, style="smooth")
            time.sleep(CLICK_HOLD_S)
            up_flag = MOUSEEVENTF_LEFTUP if button == "left" else MOUSEEVENTF_RIGHTUP
            self._send_inputs([INPUT(type=INPUT_MOUSE, union=INPUT_union(mi=MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=up_flag, time=0, dwExtraInfo=None)))])
            return ActionResult(True, "mouse_drag")
        except Exception as e:
            return ActionResult(False, "mouse_drag", str(e))

    def mouse_scroll(self, dy: int, dx: int = 0, at: Point | None = None) -> ActionResult:
        try:
            if at:
                self.mouse_move(at, style="instant")
            # WHEEL_DELTA is 120
            inp = INPUT(type=INPUT_MOUSE, union=INPUT_union(mi=MOUSEINPUT(dx=0, dy=0, mouseData=dy, dwFlags=MOUSEEVENTF_WHEEL, time=0, dwExtraInfo=None)))
            self._send_inputs([inp])
            return ActionResult(True, "mouse_scroll")
        except Exception as e:
            return ActionResult(False, "mouse_scroll", str(e))

    # ── KEYBOARD ─────────────────────────────────────────────────────────────
    def key_tap(self, keys: List[str]) -> ActionResult:
        try:
            inputs_down = []
            inputs_up = []
            for key in keys:
                vk, sc, ext = get_vk_and_scancode(key)
                flags = KEYEVENTF_SCANCODE | (KEYEVENTF_EXTENDEDKEY if ext else 0)
                inputs_down.append(INPUT(type=INPUT_KEYBOARD, union=INPUT_union(ki=KEYBDINPUT(wVk=0, wScan=sc, dwFlags=flags, time=0, dwExtraInfo=None))))
                inputs_up.insert(0, INPUT(type=INPUT_KEYBOARD, union=INPUT_union(ki=KEYBDINPUT(wVk=0, wScan=sc, dwFlags=flags | KEYEVENTF_KEYUP, time=0, dwExtraInfo=None))))

            self._send_inputs(inputs_down)
            time.sleep(CLICK_HOLD_S)
            self._send_inputs(inputs_up)
                
            return ActionResult(True, "key_tap")
        except Exception as e:
            return ActionResult(False, "key_tap", str(e))

    def type_text(self, text: str, interval_ms: int = 0, strategy: str = "auto") -> ActionResult:
        try:
            if strategy == "auto":
                non_ascii = any(ord(c) > 127 for c in text)
                strategy = "clipboard" if (len(text) > 40 or non_ascii) else "event"
                
            if strategy == "clipboard":
                import pyperclip
                old = ""
                try:
                    old = pyperclip.paste()
                except Exception:
                    pass
                try:
                    pyperclip.copy(text)
                    self.key_tap(["ctrl", "v"])
                    time.sleep(PASTE_HOLD_S)
                finally:
                    try:
                        pyperclip.copy(old)
                    except Exception:
                        pass
                return ActionResult(True, "type_text", "used clipboard")
            else:
                # Batch the WHOLE string into ONE SendInput call for instant execution
                inputs = []
                for char in text:
                    surrogates = char.encode('utf-16-le')
                    for i in range(0, len(surrogates), 2):
                        code = int.from_bytes(surrogates[i:i+2], byteorder='little')
                        inputs.append(INPUT(type=INPUT_KEYBOARD, union=INPUT_union(ki=KEYBDINPUT(wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE, time=0, dwExtraInfo=None))))
                        inputs.append(INPUT(type=INPUT_KEYBOARD, union=INPUT_union(ki=KEYBDINPUT(wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, time=0, dwExtraInfo=None))))
                self._send_inputs(inputs)
                return ActionResult(True, "type_text")
        except Exception as e:
            return ActionResult(False, "type_text", str(e))
