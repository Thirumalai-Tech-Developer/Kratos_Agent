"""Semantic GUI actions helper."""
from __future__ import annotations
from typing import Any, Dict, Optional

from kratos_agent.computer.state import ComputerAction, ActionResult
from kratos_agent.computer.executor import get_executor


def click(role: Optional[str] = None, name: Optional[str] = None, element_id: Optional[str] = None, button: str = "left") -> ActionResult:
    """Clicks an element semantically."""
    target: Dict[str, Any] = {}
    if role:
        target["role"] = role
    if name:
        target["name"] = name
    if element_id:
        target["id"] = element_id

    action = ComputerAction(action="click", target=target, parameters={"button": button})
    return get_executor().execute(action)


def type_text(text: str, role: Optional[str] = None, name: Optional[str] = None, element_id: Optional[str] = None) -> ActionResult:
    """Types text into an element semantically."""
    target: Dict[str, Any] = {}
    if role:
        target["role"] = role
    if name:
        target["name"] = name
    if element_id:
        target["id"] = element_id

    action = ComputerAction(action="type", target=target, parameters={"text": text})
    return get_executor().execute(action)
