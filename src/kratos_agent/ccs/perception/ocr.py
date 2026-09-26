
try:
    from rapidocr_onnxruntime import RapidOCR
except ImportError:
    RapidOCR = None

from kratos_agent.ccs.base import CapabilityUnavailable, ElementHandle, Rect


class OcrEngine:
    def __init__(self):
        if RapidOCR is None:
            raise CapabilityUnavailable(
                capability="OCR", 
                platform="Windows",
                hint="rapidocr-onnxruntime is not installed.",
                install="uv pip install rapidocr-onnxruntime"
            )
        self.engine = RapidOCR()

    def extract_text(self, image_path_or_bytes: str | bytes, 
                     app_context: str = "ocr", 
                     window_context: str = "screen") -> list[ElementHandle]:
        """
        Runs RapidOCR on the given image and returns ElementHandles for each text line bounding box.
        """
        result, _ = self.engine(image_path_or_bytes)
        
        elements = []
        if not result:
            return elements

        for i, (box, text, confidence) in enumerate(result):
            # box is a list of 4 points: [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
            try:
                x1 = int(min(p[0] for p in box))
                y1 = int(min(p[1] for p in box))
                x2 = int(max(p[0] for p in box))
                y2 = int(max(p[1] for p in box))
            except Exception:
                continue

            elements.append(
                ElementHandle(
                    ref=f"ocr_{i}",
                    role="Text",
                    name=text,
                    value=f"conf:{confidence:.2f}",
                    rect=Rect(x=x1, y=y1, w=x2 - x1, h=y2 - y1),
                    states=[],
                    patterns=[],
                    app=app_context,
                    window=window_context,
                    depth=0
                )
            )

        return elements
