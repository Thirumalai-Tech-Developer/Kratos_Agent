"""Visual scene interpreter and UI state understander."""
from __future__ import annotations

from typing import Any

from kratos_agent.computer.vision.detector import get_vision_detector


class VisualInterpreter:
    """Interprets screen state visually when accessibility trees or DOM are unavailable."""

    def describe_scene(self) -> dict[str, Any]:
        """Produces a structured visual summary of current screen content."""
        elements = get_vision_detector().detect_elements()
        texts = [e.name for e in elements if e.name]

        return {
            "detected_text_count": len(texts),
            "sample_texts": texts[:20],
            "has_visual_content": bool(texts),
        }
