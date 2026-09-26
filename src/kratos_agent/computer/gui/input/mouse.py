"""Mouse input engine (LOWEST PRIORITY FALLBACK)."""
from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

import sys

from kratos_agent.computer.gui.models import Point
from kratos_agent.computer.state import ActionResult

try:
    import pyautogui
except ImportError:
    pyautogui = None


class MouseEngine:
    """Low-level mouse injection engine.
    
    CRITICAL: This backend is classified as LOWEST PRIORITY (Priority 8).
    Coordinates MUST never be hallucinated or generated directly by the LLM.
    Coordinates originate exclusively from verified element bounds or vision grounding.
    """

    def __init__(self) -> None:
        if pyautogui:
            pyautogui.FAILSAFE = False

    def move(self, x: int, y: int, duration_ms: int = 0) -> ActionResult:
        """Moves the mouse cursor to (x, y)."""
        if sys.platform == "win32":
            try:
                from kratos_agent.ccs.input.windows import WindowsInputEngine
                engine = WindowsInputEngine(humanize=False)
                return engine.mouse_move(Point(x, y), duration_ms=duration_ms)
            except Exception as exc:
                logger.debug("Operation error suppressed: %s", exc)

        if pyautogui:
            pyautogui.moveTo(x, y, duration=duration_ms / 1000.0 if duration_ms else 0.0)
            return ActionResult(ok=True, action="mouse_move", data={"x": x, "y": y}, method_used="mouse_coordinate")

        return ActionResult(ok=False, action="mouse_move", detail="No mouse driver available")

    def click(
        self,
        x: int | None = None,
        y: int | None = None,
        button: str = "left",
        clicks: int = 1,
        modifiers: list[str] | None = None,
    ) -> ActionResult:
        """Clicks the mouse at specified or current coordinates."""
        pt = Point(x, y) if x is not None and y is not None else None

        if sys.platform == "win32":
            try:
                from kratos_agent.ccs.input.windows import WindowsInputEngine
                engine = WindowsInputEngine(humanize=False)
                return engine.mouse_click(p=pt, button=button, clicks=clicks, modifiers=modifiers or [])
            except Exception as exc:
                logger.debug("Operation error suppressed: %s", exc)

        if pyautogui:
            if pt:
                pyautogui.moveTo(pt.x, pt.y)
            if clicks == 2 and button == "left":
                pyautogui.doubleClick(button=button)
            else:
                pyautogui.click(button=button, clicks=clicks)
            return ActionResult(ok=True, action="mouse_click", data={"x": x, "y": y, "button": button, "clicks": clicks}, method_used="mouse_coordinate")

        return ActionResult(ok=False, action="mouse_click", detail="No mouse driver available")

    def double_click(self, x: int | None = None, y: int | None = None) -> ActionResult:
        return self.click(x=x, y=y, button="left", clicks=2)

    def right_click(self, x: int | None = None, y: int | None = None) -> ActionResult:
        return self.click(x=x, y=y, button="right", clicks=1)

    def drag(self, from_x: int, from_y: int, to_x: int, to_y: int, button: str = "left", duration_ms: int = 200) -> ActionResult:
        """Drags mouse from (from_x, from_y) to (to_x, to_y)."""
        if sys.platform == "win32":
            try:
                from kratos_agent.ccs.input.windows import WindowsInputEngine
                engine = WindowsInputEngine(humanize=False)
                return engine.mouse_drag(Point(from_x, from_y), Point(to_x, to_y), button=button, duration_ms=duration_ms)
            except Exception as exc:
                logger.debug("Operation error suppressed: %s", exc)

        if pyautogui:
            pyautogui.moveTo(from_x, from_y)
            pyautogui.dragTo(to_x, to_y, duration=duration_ms / 1000.0, button=button)
            return ActionResult(ok=True, action="mouse_drag", data={"from": [from_x, from_y], "to": [to_x, to_y]}, method_used="mouse_coordinate")

        return ActionResult(ok=False, action="mouse_drag", detail="No mouse driver available")

    def scroll(self, dy: int, dx: int = 0, x: int | None = None, y: int | None = None) -> ActionResult:
        """Scrolls mouse wheel vertically or horizontally."""
        pt = Point(x, y) if x is not None and y is not None else None
        if sys.platform == "win32":
            try:
                from kratos_agent.ccs.input.windows import WindowsInputEngine
                engine = WindowsInputEngine(humanize=False)
                return engine.mouse_scroll(dy=dy, dx=dx, at=pt)
            except Exception as exc:
                logger.debug("Operation error suppressed: %s", exc)

        if pyautogui:
            if pt:
                pyautogui.moveTo(pt.x, pt.y)
            pyautogui.scroll(dy)
            return ActionResult(ok=True, action="mouse_scroll", data={"dy": dy, "dx": dx}, method_used="mouse_coordinate")

        return ActionResult(ok=False, action="mouse_scroll", detail="No mouse driver available")
