"""High-level semantic GUI tools."""
from __future__ import annotations
import json
from typing import Any, Dict, Optional

from kratos_agent.computer.gui.manager import get_gui_manager


def gui_find(query: str, role: Optional[str] = None) -> str:
    """Finds a UI element matching query and/or role."""
    gm = get_gui_manager()
    try:
        elem = gm.find(query=query, role=role)
        return json.dumps(elem.to_dict(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=2)


def gui_click(role: Optional[str] = None, name: Optional[str] = None, element_id: Optional[str] = None) -> str:
    """Clicks a UI element semantically."""
    gm = get_gui_manager()
    res = gm.click(role=role, name=name, element_id=element_id)
    return json.dumps(res.to_dict(), indent=2)


def gui_type(text: str, role: Optional[str] = None, name: Optional[str] = None, element_id: Optional[str] = None) -> str:
    """Types text into a UI element semantically."""
    gm = get_gui_manager()
    res = gm.type(text=text, role=role, name=name, element_id=element_id)
    return json.dumps(res.to_dict(), indent=2)
