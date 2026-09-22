"""Playwright / Browser DOM backend for GUI automation."""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from kratos_agent.computer.gui.backends.base import GUIBackend
from kratos_agent.computer.gui.models import GUIElement, Rect, Point
from kratos_agent.computer.state import ActionResult
from kratos_agent.computer.browser.playwright import PlaywrightDriver


class PlaywrightBackend(GUIBackend):
    """Browser DOM GUI backend operating on web pages."""

    def __init__(self) -> None:
        self._driver = PlaywrightDriver()

    @property
    def name(self) -> str:
        return "playwright"

    @property
    def priority(self) -> int:
        return 3  # Browser DOM = Priority 3

    def is_available(self) -> bool:
        return self._driver.is_available()

    def dump_tree(
        self,
        app: Optional[str] = None,
        root_window: Optional[str] = None,
        max_depth: int = 8,
        max_nodes: int = 400,
        visible_only: bool = True,
    ) -> List[GUIElement]:
        if not self.is_available():
            return []

        raw_elements = self._driver.dump_interactive_dom()
        elements: List[GUIElement] = []
        for item in raw_elements[:max_nodes]:
            elem = GUIElement(
                id=item["id"],
                name=item.get("name", ""),
                role=item.get("role", "element"),
                control_type=item.get("tag", "tag"),
                text=item.get("name", ""),
                enabled=not item.get("disabled", False),
                visible=True,
                focused=False,
                bounds=item.get("bounds"),
                backend="playwright",
                confidence=0.98,
            )
            elements.append(elem)
        return elements

    def find_elements(
        self,
        query: Optional[str] = None,
        role: Optional[str] = None,
        app: Optional[str] = None,
        limit: int = 25,
    ) -> List[GUIElement]:
        tree = self.dump_tree(max_nodes=300)
        q_lower = query.lower() if query else None
        role_lower = role.lower() if role else None

        matches: List[GUIElement] = []
        for el in tree:
            match = True
            if q_lower:
                match = q_lower in (el.name or "").lower() or q_lower in (el.text or "").lower()
            if match and role_lower:
                match = role_lower in (el.role or "").lower()
            if match:
                matches.append(el)
                if len(matches) >= limit:
                    break
        return matches

    def find_element(
        self,
        query: Optional[str] = None,
        role: Optional[str] = None,
        app: Optional[str] = None,
    ) -> Optional[GUIElement]:
        matches = self.find_elements(query=query, role=role, limit=1)
        return matches[0] if matches else None

    def invoke_element(
        self,
        element: GUIElement,
        pattern: str = "Invoke",
        value: Optional[str] = None,
    ) -> ActionResult:
        if pattern.lower() in ("value", "set_value", "type") and value is not None:
            return self.type_element(element, value)
        return self.click_element(element)

    def click_element(
        self,
        element: GUIElement,
        button: str = "left",
        clicks: int = 1,
    ) -> ActionResult:
        return self._driver.click(role=element.role, name=element.name)

    def type_element(
        self,
        element: GUIElement,
        text: str,
        clear_first: bool = False,
    ) -> ActionResult:
        return self._driver.fill(text=text, role=element.role, name=element.name)
