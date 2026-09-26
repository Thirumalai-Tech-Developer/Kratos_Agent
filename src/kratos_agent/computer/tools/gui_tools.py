"""High-level semantic GUI tools."""
from __future__ import annotations

import json

from kratos_agent.computer.gui.manager import get_gui_manager


def gui_find(query: str, role: str | None = None) -> str:
    """Finds a UI element matching query and/or role."""
    gm = get_gui_manager()
    try:
        elem = gm.find(query=query, role=role)
        return json.dumps(elem.to_dict(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=2)


def gui_click(role: str | None = None, name: str | None = None, element_id: str | None = None) -> str:
    """Clicks a UI element semantically."""
    gm = get_gui_manager()
    res = gm.click(role=role, name=name, element_id=element_id)
    return json.dumps(res.to_dict(), indent=2)


def gui_type(text: str, role: str | None = None, name: str | None = None, element_id: str | None = None) -> str:
    """Types text into a UI element semantically."""
    gm = get_gui_manager()
    res = gm.type(text=text, role=role, name=name, element_id=element_id)
    return json.dumps(res.to_dict(), indent=2)
