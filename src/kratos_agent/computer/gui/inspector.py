"""GUI element tree inspector and pruning engine."""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from kratos_agent.computer.gui.models import GUIElement


class GUIInspector:
    """Inspects and filters GUI trees to extract interactive controls while minimizing token consumption."""

    INTERACTIVE_ROLES = {
        "button",
        "edit",
        "textbox",
        "checkbox",
        "radiobutton",
        "combobox",
        "listitem",
        "menuitem",
        "tabitem",
        "hyperlink",
        "link",
        "slider",
        "spinner",
        "document",
        "pane",
    }

    def filter_interactive(self, elements: List[GUIElement], max_elements: int = 150) -> List[GUIElement]:
        """Prunes structural or invisible nodes, retaining only interactive controls."""
        filtered: List[GUIElement] = []

        for el in elements:
            if not el.visible or not el.enabled:
                continue

            role_lower = (el.role or "").lower()
            # If role is interactive or has explicit name/value
            if any(ir in role_lower for ir in self.INTERACTIVE_ROLES) or el.name:
                filtered.append(el)
                if len(filtered) >= max_elements:
                    break

        return filtered

    def summarize_tree(self, elements: List[GUIElement]) -> str:
        """Serializes pruned elements into a compact, human/LLM-readable text format."""
        lines = []
        for el in elements:
            bounds_str = f"[{el.bounds['x']},{el.bounds['y']}]" if el.bounds else "[no-bounds]"
            name_str = f"'{el.name}'" if el.name else "unnamed"
            val_str = f" value='{el.value}'" if el.value else ""
            lines.append(f"{el.id}: {el.role} {name_str}{val_str} {bounds_str} (backend={el.backend})")

        return "\n".join(lines) if lines else "(No interactive elements found)"


_inspector: Optional[GUIInspector] = None


def get_inspector() -> GUIInspector:
    global _inspector
    if _inspector is None:
        _inspector = GUIInspector()
    return _inspector
