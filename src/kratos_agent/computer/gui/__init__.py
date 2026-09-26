"""GUI subsystem for semantic element inspection, resolution, and action."""
from __future__ import annotations

from kratos_agent.computer.gui.errors import ComputerError, FailureType
from kratos_agent.computer.gui.models import (
    DisplayInfo,
    GUIElement,
    Point,
    Rect,
    WindowInfo,
)
from kratos_agent.computer.gui.resolver import SemanticResolver, get_resolver
from kratos_agent.computer.gui.selectors import ElementSelector

__all__ = [
    "ComputerError",
    "DisplayInfo",
    "ElementSelector",
    "FailureType",
    "GUIElement",
    "Point",
    "Rect",
    "SemanticResolver",
    "WindowInfo",
    "get_resolver",
]
