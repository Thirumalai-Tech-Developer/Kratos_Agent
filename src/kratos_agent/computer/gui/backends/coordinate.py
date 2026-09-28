"""Coordinate-based fallback GUI backend (LOWEST PRIORITY)."""
from __future__ import annotations

from kratos_agent.computer.gui.backends.base import GUIBackend
from kratos_agent.computer.gui.models import GUIElement
from kratos_agent.computer.state import ActionResult


class CoordinateBackend(GUIBackend):
    """Compatibility shell for the disabled coordinate-input backend."""

    @property
    def name(self) -> str:
        return "coordinate"

    @property
    def priority(self) -> int:
        return 8  # Lowest priority fallback

    def is_available(self) -> bool:
        return False

    def dump_tree(
        self,
        app: str | None = None,
        root_window: str | None = None,
        max_depth: int = 8,
        max_nodes: int = 400,
        visible_only: bool = True,
    ) -> list[GUIElement]:
        # Coordinate backend does not expose an object tree.
        return []

    def find_elements(
        self,
        query: str | None = None,
        role: str | None = None,
        app: str | None = None,
        limit: int = 25,
    ) -> list[GUIElement]:
        return []

    def find_element(
        self,
        query: str | None = None,
        role: str | None = None,
        app: str | None = None,
    ) -> GUIElement | None:
        return None

    def invoke_element(
        self,
        element: GUIElement,
        pattern: str = "Invoke",
        value: str | None = None,
    ) -> ActionResult:
        return self.click_element(element)

    def click_element(
        self,
        element: GUIElement,
        button: str = "left",
        clicks: int = 1,
    ) -> ActionResult:
        return ActionResult(
            ok=False,
            action="coordinate_click",
            detail="Coordinate input is disabled; resolve an accessible control or use keyboard navigation.",
        )

    def type_element(
        self,
        element: GUIElement,
        text: str,
        clear_first: bool = False,
    ) -> ActionResult:
        return ActionResult(
            ok=False,
            action="coordinate_type",
            detail="Coordinate input is disabled; resolve an accessible control or use keyboard navigation.",
        )
