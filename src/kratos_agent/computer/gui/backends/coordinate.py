"""Coordinate-based fallback GUI backend (LOWEST PRIORITY)."""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from kratos_agent.computer.gui.backends.base import GUIBackend
from kratos_agent.computer.gui.models import GUIElement, Rect, Point
from kratos_agent.computer.state import ActionResult
from kratos_agent.computer.gui.input.mouse import MouseEngine
from kratos_agent.computer.gui.input.keyboard import KeyboardEngine


class CoordinateBackend(GUIBackend):
    """Raw coordinate GUI fallback backend.
    
    CRITICAL: Priority 8 (lowest). Only invoked when semantic methods,
    accessibility, DOM, keyboard navigation, and vision have failed.
    """

    def __init__(self) -> None:
        self._mouse = MouseEngine()
        self._keyboard = KeyboardEngine()

    @property
    def name(self) -> str:
        return "coordinate"

    @property
    def priority(self) -> int:
        return 8  # Lowest priority fallback

    def is_available(self) -> bool:
        return True

    def dump_tree(
        self,
        app: Optional[str] = None,
        root_window: Optional[str] = None,
        max_depth: int = 8,
        max_nodes: int = 400,
        visible_only: bool = True,
    ) -> List[GUIElement]:
        # Coordinate backend does not expose an object tree
        return []

    def find_elements(
        self,
        query: Optional[str] = None,
        role: Optional[str] = None,
        app: Optional[str] = None,
        limit: int = 25,
    ) -> List[GUIElement]:
        return []

    def find_element(
        self,
        query: Optional[str] = None,
        role: Optional[str] = None,
        app: Optional[str] = None,
    ) -> Optional[GUIElement]:
        return None

    def invoke_element(
        self,
        element: GUIElement,
        pattern: str = "Invoke",
        value: Optional[str] = None,
    ) -> ActionResult:
        return self.click_element(element)

    def click_element(
        self,
        element: GUIElement,
        button: str = "left",
        clicks: int = 1,
    ) -> ActionResult:
        if element.center:
            return self._mouse.click(x=element.center.x, y=element.center.y, button=button, clicks=clicks)
        return ActionResult(ok=False, action="coordinate_click", detail="Element lacks bounding coordinates")

    def type_element(
        self,
        element: GUIElement,
        text: str,
        clear_first: bool = False,
    ) -> ActionResult:
        if element.center:
            self._mouse.click(x=element.center.x, y=element.center.y)
        if clear_first:
            self._keyboard.hotkey("ctrl", "a")
            self._keyboard.key_tap(["backspace"])
        return self._keyboard.type_text(text)
