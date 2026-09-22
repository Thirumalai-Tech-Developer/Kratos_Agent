"""GUI subsystem for semantic element inspection, resolution, and action."""
from __future__ import annotations

from kratos_agent.computer.gui.models import GUIElement, Rect, Point, WindowInfo, DisplayInfo
from kratos_agent.computer.gui.selectors import ElementSelector
from kratos_agent.computer.gui.resolver import SemanticResolver, get_resolver
from kratos_agent.computer.gui.errors import FailureType, ComputerError

__all__ = [
    "GUIElement",
    "Rect",
    "Point",
    "WindowInfo",
    "DisplayInfo",
    "ElementSelector",
    "SemanticResolver",
    "get_resolver",
    "FailureType",
    "ComputerError",
]
