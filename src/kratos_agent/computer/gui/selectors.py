"""Element selector query matching engine."""
from __future__ import annotations
import re
from typing import Any, Dict, Optional

from kratos_agent.computer.gui.models import GUIElement


class ElementSelector:
    """Matches GUI elements against multi-attribute selector criteria."""

    def __init__(
        self,
        name: Optional[str] = None,
        role: Optional[str] = None,
        control_type: Optional[str] = None,
        text: Optional[str] = None,
        element_id: Optional[str] = None,
        backend: Optional[str] = None,
        regex: bool = False,
    ) -> None:
        self.name = name
        self.role = role
        self.control_type = control_type
        self.text = text
        self.element_id = element_id
        self.backend = backend
        self.regex = regex

    def matches(self, element: GUIElement) -> Tuple[bool, float]:
        """Returns (matched: bool, score: float). Score is between 0.0 and 1.0."""
        score = 0.0
        weight_total = 0.0

        # Exact ID match -> 1.0
        if self.element_id:
            if element.id.lower() == self.element_id.lower():
                return True, 1.0
            return False, 0.0

        # Backend filter
        if self.backend and element.backend.lower() != self.backend.lower():
            return False, 0.0

        # Role match
        if self.role:
            weight_total += 0.3
            el_role = (element.role or "").lower()
            target_role = self.role.lower()
            if target_role == el_role:
                score += 0.3
            elif target_role in el_role:
                score += 0.2
            else:
                return False, 0.0

        # Name match
        if self.name:
            weight_total += 0.5
            el_name = (element.name or "").lower()
            target_name = self.name.lower()
            if self.regex:
                if re.search(self.name, element.name or "", re.IGNORECASE):
                    score += 0.5
                else:
                    return False, 0.0
            else:
                if target_name == el_name:
                    score += 0.5
                elif target_name in el_name:
                    score += 0.4
                elif any(word in el_name for word in target_name.split() if len(word) > 2):
                    score += 0.25
                else:
                    return False, 0.0

        # Text / Value match
        if self.text:
            weight_total += 0.2
            el_text = (element.text or element.value or "").lower()
            target_text = self.text.lower()
            if target_text == el_text:
                score += 0.2
            elif target_text in el_text:
                score += 0.15

        if weight_total == 0.0:
            return True, 0.5

        final_confidence = min(1.0, score / weight_total)
        return (final_confidence >= 0.5), final_confidence
