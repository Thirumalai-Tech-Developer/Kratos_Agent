"""Fast screen diff computation to detect UI changes following actions.
Budget: <= 60 ms.
"""
from __future__ import annotations
import io
from typing import Optional, Tuple
try:
    from PIL import Image, ImageChops
except ImportError:
    Image = None
    ImageChops = None

def compute_screen_diff(
    frame_a_bytes: bytes,
    frame_b_bytes: bytes,
    min_changed_px: int = 64,
    threshold: int = 25,
) -> Tuple[bool, int]:
    """Compares two frames and returns (changed: bool, changed_px: int).
    Downsamples to grayscale for high performance (typically < 30 ms).
    """
    if not Image or not ImageChops:
        # If PIL is not installed, assume changed to prevent blocking
        return True, min_changed_px + 1

    try:
        img_a = Image.open(io.BytesIO(frame_a_bytes)).convert("L")
        img_b = Image.open(io.BytesIO(frame_b_bytes)).convert("L")

        # Downscale for rapid diffing if large
        max_dim = 1000
        if max(img_a.size) > max_dim:
            img_a.thumbnail((max_dim, max_dim))
            img_b.thumbnail((max_dim, max_dim))

        diff = ImageChops.difference(img_a, img_b)
        # Apply threshold
        diff_bin = diff.point(lambda p: 255 if p > threshold else 0)
        # Count non-zero pixels
        hist = diff_bin.histogram()
        changed_pixels = sum(hist[1:])

        return changed_pixels >= min_changed_px, changed_pixels
    except Exception:
        return True, min_changed_px + 1
