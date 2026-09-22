"""Keyboard input engine with native Win32 SendInput and cross-platform fallbacks."""
from __future__ import annotations
import sys
import time
from typing import List, Optional

from kratos_agent.computer.state import ActionResult

try:
    import pyautogui
except ImportError:
    pyautogui = None


class KeyboardEngine:
    """High-reliability keyboard engine for shortcuts, text entry, and modifier keys."""

    def __init__(self) -> None:
        if pyautogui:
            pyautogui.FAILSAFE = False

    def key_tap(self, keys: List[str]) -> ActionResult:
        """Taps a key combination or sequence (e.g. ['ctrl', 'v'] or ['enter'])."""
        if sys.platform == "win32":
            try:
                from kratos_agent.ccs.input.windows import WindowsInputEngine
                engine = WindowsInputEngine(humanize=False)
                return engine.key_tap(keys)
            except Exception:
                pass

        if pyautogui:
            try:
                if len(keys) == 1:
                    pyautogui.press(keys[0].lower())
                else:
                    pyautogui.hotkey(*[k.lower() for k in keys])
                return ActionResult(ok=True, action="key_tap", detail=f"Pressed {'+'.join(keys)}")
            except Exception as e:
                return ActionResult(ok=False, action="key_tap", detail=str(e))

        return ActionResult(ok=False, action="key_tap", detail="No keyboard input driver available")

    def hotkey(self, *keys: str) -> ActionResult:
        """Convenience method to press a hotkey combination (e.g. hotkey('ctrl', 'shift', 'p'))."""
        return self.key_tap(list(keys))

    def type_text(self, text: str, interval_ms: int = 0, strategy: str = "auto") -> ActionResult:
        """Types Unicode or ASCII text safely using batch injection or clipboard paste."""
        if sys.platform == "win32":
            try:
                from kratos_agent.ccs.input.windows import WindowsInputEngine
                engine = WindowsInputEngine(humanize=False)
                return engine.type_text(text, interval_ms=interval_ms, strategy=strategy)
            except Exception:
                pass

        if pyautogui:
            try:
                pyautogui.write(text, interval=interval_ms / 1000.0 if interval_ms else 0.0)
                return ActionResult(ok=True, action="type_text", detail=f"Typed {len(text)} chars")
            except Exception as e:
                return ActionResult(ok=False, action="type_text", detail=str(e))

        return ActionResult(ok=False, action="type_text", detail="No keyboard input driver available")

    def press(self, key: str) -> ActionResult:
        """Presses a single key."""
        return self.key_tap([key])
