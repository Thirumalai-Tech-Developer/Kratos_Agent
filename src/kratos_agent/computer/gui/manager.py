"""GUIManager orchestrating GUI inspection, resolution, and actions."""
from __future__ import annotations

from kratos_agent.computer.gui.actions import click, type_text
from kratos_agent.computer.gui.inspector import get_inspector
from kratos_agent.computer.gui.models import GUIElement
from kratos_agent.computer.gui.resolver import get_resolver
from kratos_agent.computer.state import ActionResult


class GUIManager:
    """Manages GUI element resolution, inspection, and high-level actions."""

    def __init__(self) -> None:
        self.resolver = get_resolver()
        self.inspector = get_inspector()

    def find(self, query: str | None = None, role: str | None = None, name: str | None = None) -> GUIElement:
        """Finds a single GUI element using semantic resolution."""
        target = {}
        if name or query:
            target["name"] = name or query
        if role:
            target["role"] = role
        return self.resolver.resolve(target)

    def click(self, role: str | None = None, name: str | None = None, element_id: str | None = None) -> ActionResult:
        """Clicks an element semantically."""
        return click(role=role, name=name, element_id=element_id)

    def type(self, text: str, role: str | None = None, name: str | None = None, element_id: str | None = None) -> ActionResult:
        """Types text into an element semantically."""
        return type_text(text=text, role=role, name=name, element_id=element_id)


_gui_manager: GUIManager | None = None


def get_gui_manager() -> GUIManager:
    global _gui_manager
    if _gui_manager is None:
        _gui_manager = GUIManager()
    return _gui_manager
