"""Vision grounding engine mapping visual regions to semantic actions."""
from __future__ import annotations

from kratos_agent.computer.gui.models import GUIElement
from kratos_agent.computer.vision.detector import get_vision_detector


class VisionGrounding:
    """Grounds visual search queries into concrete bounding regions.
    
    CRITICAL: Coordinates are generated internally by the vision system,
    NEVER hallucinated or invented by the LLM.
    Before clicking, always attempt semantic resolution again.
    """

    def find_visual_target(self, query: str) -> GUIElement | None:
        """Finds a visual target on screen matching the text query."""
        elements = get_vision_detector().detect_elements()
        q_lower = query.lower()

        # 1. Exact match
        for el in elements:
            if (el.name or "").lower() == q_lower:
                return el

        # 2. Substring match
        for el in elements:
            if q_lower in (el.name or "").lower():
                return el

        return None


_vision_grounding: VisionGrounding | None = None


def get_vision_grounding() -> VisionGrounding:
    global _vision_grounding
    if _vision_grounding is None:
        _vision_grounding = VisionGrounding()
    return _vision_grounding
