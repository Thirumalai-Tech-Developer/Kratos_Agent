"""Linux AT-SPI accessibility backend."""
from __future__ import annotations
import sys
from typing import Any, Dict, List, Optional

from kratos_agent.computer.gui.backends.base import GUIBackend
from kratos_agent.computer.gui.models import GUIElement, Rect, Point
from kratos_agent.computer.state import ActionResult


class LinuxATSPIBackend(GUIBackend):
    """Linux AT-SPI (Assistive Technology Service Provider Interface) backend."""

    def __init__(self) -> None:
        self._available: Optional[bool] = None
        self._atspi: Any = None

    @property
    def name(self) -> str:
        return "linux_atspi"

    @property
    def priority(self) -> int:
        return 2  # Accessibility API = Priority 2

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        if sys.platform != "linux":
            self._available = False
            return False

        try:
            import pyatspi
            self._atspi = pyatspi
            self._available = True
        except ImportError:
            self._available = False

        return self._available

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

        elements: List[GUIElement] = []
        elem_id_counter = [1]

        def traverse(node: Any, depth: int) -> None:
            if depth > max_depth or len(elements) >= max_nodes or not node:
                return

            try:
                role_name = node.get_role_name()
                name = node.name or ""
                description = node.description or ""
                states = [s.value_name for s in node.get_state_set().get_states()]
                visible = "visible" in states or "showing" in states

                if visible_only and not visible:
                    return

                # Bounding box
                bbox = node.get_extents(self._atspi.XY_SCREEN)
                r = {"x": bbox.x, "y": bbox.y, "w": bbox.width, "h": bbox.height}

                elem_id = f"atspi_{elem_id_counter[0]}"
                elem_id_counter[0] += 1

                elem = GUIElement(
                    id=elem_id,
                    name=name,
                    role=role_name,
                    control_type=role_name,
                    text=name,
                    description=description if description else None,
                    enabled="enabled" in states or "sensitive" in states,
                    visible=visible,
                    focused="focused" in states,
                    bounds=r,
                    backend="linux_atspi",
                    confidence=0.98,
                )
                elements.append(elem)

                for i in range(node.child_count):
                    traverse(node.get_child_at_index(i), depth + 1)
            except Exception:
                pass

        try:
            reg = self._atspi.Registry
            for i in range(reg.get_desktop_count()):
                desktop = reg.get_desktop(i)
                for j in range(desktop.child_count):
                    app_node = desktop.get_child_at_index(j)
                    if app and app.lower() not in (app_node.name or "").lower():
                        continue
                    traverse(app_node, 0)
        except Exception:
            pass

        return elements

    def find_elements(
        self,
        query: Optional[str] = None,
        role: Optional[str] = None,
        app: Optional[str] = None,
        limit: int = 25,
    ) -> List[GUIElement]:
        tree = self.dump_tree(app=app, max_nodes=500)
        q_lower = query.lower() if query else None
        role_lower = role.lower() if role else None

        matches: List[GUIElement] = []
        for el in tree:
            match = True
            if q_lower:
                el_name = (el.name or "").lower()
                el_text = (el.text or "").lower()
                match = (q_lower in el_name) or (q_lower in el_text)
            if match and role_lower:
                el_role = (el.role or "").lower()
                match = (role_lower == el_role) or (role_lower in el_role)
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
        matches = self.find_elements(query=query, role=role, app=app, limit=1)
        return matches[0] if matches else None

    def invoke_element(
        self,
        element: GUIElement,
        pattern: str = "Invoke",
        value: Optional[str] = None,
    ) -> ActionResult:
        # AT-SPI action interface
        if not self.is_available():
            return ActionResult(ok=False, action="invoke_element", detail="Linux AT-SPI unavailable")

        return ActionResult(ok=False, action="invoke_element", detail="AT-SPI semantic action is unavailable for this element; coordinate input is disabled")

    def click_element(
        self,
        element: GUIElement,
        button: str = "left",
        clicks: int = 1,
    ) -> ActionResult:
        return ActionResult(ok=False, action="click_element", detail="AT-SPI semantic activation is unavailable; coordinate input is disabled")

    def type_element(
        self,
        element: GUIElement,
        text: str,
        clear_first: bool = False,
    ) -> ActionResult:
        return ActionResult(ok=False, action="type_element", detail="AT-SPI semantic text entry is unavailable; coordinate input is disabled")
