"""Semantic GUI actions helper."""
from __future__ import annotations

from typing import Any

from kratos_agent.computer.executor import get_executor
from kratos_agent.computer.state import ActionResult, ComputerAction


def click(role: str | None = None, name: str | None = None, element_id: str | None = None, button: str = "left") -> ActionResult:
    """Clicks an element semantically."""
    target: dict[str, Any] = {}
    if role:
        target["role"] = role
    if name:
        target["name"] = name
    if element_id:
        target["id"] = element_id

    action = ComputerAction(action="click", target=target, parameters={"button": button})
    return get_executor().execute(action)


def type_text(text: str, role: str | None = None, name: str | None = None, element_id: str | None = None) -> ActionResult:
    """Types text into an element semantically."""
    target: dict[str, Any] = {}
    if role:
        target["role"] = role
    if name:
        target["name"] = name
    if element_id:
        target["id"] = element_id

    action = ComputerAction(action="type", target=target, parameters={"text": text})
    return get_executor().execute(action)
