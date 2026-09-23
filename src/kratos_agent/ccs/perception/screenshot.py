import ctypes
import os
import time
from pathlib import Path
from typing import Optional, Tuple
try:
    from mss import mss
    _HAS_MSS = True
except ImportError:
    _HAS_MSS = False

from PIL import Image
import io

from kratos_agent.ccs.base import Rect, CapabilityUnavailable

# Call this very early to prevent Windows from lying about screen coordinates.
# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
except Exception:
    pass # Ignore on older OS

def take_screenshot(monitor: Optional[int] = None, region: Optional[Rect] = None, 
                   max_long_edge: int = 1568, save_dir: Optional[Path] = None,
                   include_cursor: bool = False, downscale: int = 0) -> Tuple[bytes, str]:
    """
    Takes a screenshot using mss (or ImageGrab fallback), downscales if necessary, and saves to disk.
    Returns (PNG bytes, frame_id).
    """
    img = None
    if _HAS_MSS:
        try:
            with mss() as sct:
                if region:
                    monitor_dict = {"top": region.y, "left": region.x, "width": region.w, "height": region.h}
                elif monitor is not None and monitor < len(sct.monitors):
                    monitor_dict = sct.monitors[monitor]
                else:
                    monitor_dict = sct.monitors[0]

                sct_img = sct.grab(monitor_dict)
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        except Exception:
            pass
    if img is None:

        try:
            from PIL import ImageGrab
            if region:
                img = ImageGrab.grab(bbox=(region.x, region.y, region.x + region.w, region.y + region.h), all_screens=True)
            else:
                img = ImageGrab.grab(all_screens=True)
        except Exception:
            w_fallback = region.w if region else 1920
            h_fallback = region.h if region else 1080
            img = Image.new("RGB", (w_fallback, h_fallback), color=(30, 30, 30))

        # Downscale if needed
        w, h = img.size
        if max(w, h) > max_long_edge:
            if w > h:
                new_w = max_long_edge
                new_h = int(h * (max_long_edge / w))
            else:
                new_h = max_long_edge
                new_w = int(w * (max_long_edge / h))
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        # Generate Frame ID
        frame_id = f"frame_{int(time.time() * 1000)}"
        
        # Save to disk
        if not save_dir:
            save_dir = Path(".kratos") / "ccs" / "frames"
        save_dir.mkdir(parents=True, exist_ok=True)
        img.save(save_dir / f"{frame_id}.png", format="PNG")

        # Return bytes
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        
        return img_byte_arr.getvalue(), frame_id
