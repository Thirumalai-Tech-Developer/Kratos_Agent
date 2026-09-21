from typing import List, Optional
from kratos_agent.ccs.base import ElementHandle, Rect
from kratos_agent.ccs.perception.a11y_windows import WindowsA11yEngine
from kratos_agent.ccs.perception.ocr import OcrEngine

class GroundingEngine:
    def __init__(self, a11y: WindowsA11yEngine, ocr: OcrEngine):
        self.a11y = a11y
        self.ocr = ocr
        self._last_elements: List[ElementHandle] = []

    def refresh_scene(self, image_path_or_bytes: str | bytes) -> List[ElementHandle]:
        """Runs A11y and OCR to build a combined representation of the current screen."""
        elements = []
        
        # 1. Get A11y Elements
        try:
            a11y_elements = self.a11y.dump_tree()
            elements.extend(a11y_elements)
        except Exception as e:
            print(f"Warning: A11y failed: {e}")

        # 2. Get OCR Elements
        try:
            ocr_elements = self.ocr.extract_text(image_path_or_bytes)
            # Offset the OCR refs to avoid collision if needed, but they start with "ocr_"
            elements.extend(ocr_elements)
        except Exception as e:
            print(f"Warning: OCR failed: {e}")

        self._last_elements = elements
        return elements

    def find_element(self, query: str) -> Optional[ElementHandle]:
        """
        Implements the resolution ladder:
        1. Exact reference ID match (e.g. 'e17', 'ocr_5')
        2. Exact Name match (A11y or OCR)
        3. Substring Name match
        """
        if not self._last_elements:
            return None

        # 1. Exact Ref
        for el in self._last_elements:
            if el.ref.lower() == query.lower():
                return el

        # 2. Exact Name
        for el in self._last_elements:
            if el.name and el.name.lower() == query.lower():
                return el
                
        # 3. Substring Name
        for el in self._last_elements:
            if el.name and query.lower() in el.name.lower():
                return el

        return None
