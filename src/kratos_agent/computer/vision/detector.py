"""Vision-based UI element detector using OCR and screen analysis."""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from kratos_agent.computer.gui.models import GUIElement, Rect, Point
from kratos_agent.ccs.perception.screenshot import take_screenshot
from kratos_agent.ccs.perception.ocr import OcrEngine


class VisionDetector:
    """Detects UI controls and text from screen captures."""

    def __init__(self) -> None:
        self._ocr: Optional[OcrEngine] = None
        try:
            self._ocr = OcrEngine()
        except Exception:
            self._ocr = None

    def detect_elements(self, screenshot_bytes: Optional[bytes] = None) -> List[GUIElement]:
        """Runs visual detection / OCR on screen to identify interactive elements."""
        if not screenshot_bytes:
            try:
                screenshot_bytes, _ = take_screenshot()
            except Exception:
                return []

        if not self._ocr:
            return []

        try:
            ocr_elements = self._ocr.extract_text(screenshot_bytes)
            gui_elements: List[GUIElement] = []
            for item in ocr_elements:
                r = {"x": item.rect.x, "y": item.rect.y, "w": item.rect.w, "h": item.rect.h}
                elem = GUIElement(
                    id=item.ref,
                    name=item.name,
                    role="visual_text",
                    control_type="text",
                    text=item.name,
                    bounds=r,
                    backend="vision",
                    confidence=0.80,
                )
                gui_elements.append(elem)
            return gui_elements
        except Exception:
            return []


_vision_detector: Optional[VisionDetector] = None


def get_vision_detector() -> VisionDetector:
    global _vision_detector
    if _vision_detector is None:
        _vision_detector = VisionDetector()
    return _vision_detector
