"""Bounded screen capture persistence."""
from __future__ import annotations

import io
import os
import threading
import time
from pathlib import Path
from typing import Optional, Tuple
import uuid

try:
    from mss import mss
    _HAS_MSS = True
except ImportError:
    _HAS_MSS = False

from PIL import Image, ImageDraw
from kratos_agent.ccs.base import Rect

_FRAME_LOCK = threading.Lock()
_DEFAULT_FRAME_DIR = Path(".kratos") / "ccs" / "frames"
_DEFAULT_MAX_COUNT = 100
_DEFAULT_MAX_BYTES = 64 * 1024 * 1024
_DEFAULT_MAX_AGE_S = 60 * 60

def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default

def get_frame_store_dir(save_dir: Optional[Path] = None) -> Path:
    return Path(save_dir or os.getenv("KRATOS_FRAME_DIR") or _DEFAULT_FRAME_DIR).expanduser()

def cleanup_frame_store(save_dir: Optional[Path] = None, keep_refs: Optional[set[str]] = None,
                       max_count: Optional[int] = None, max_bytes: Optional[int] = None,
                       max_age_s: Optional[int] = None) -> dict:
    """Delete old screenshot evidence so frame storage remains bounded."""
    root = get_frame_store_dir(save_dir)
    root.mkdir(parents=True, exist_ok=True)
    keep = set(keep_refs or set())
    max_count = max_count or _env_int("KRATOS_FRAME_MAX_COUNT", _DEFAULT_MAX_COUNT)
    max_bytes = max_bytes or _env_int("KRATOS_FRAME_MAX_BYTES", _DEFAULT_MAX_BYTES)
    max_age_s = max_age_s or _env_int("KRATOS_FRAME_MAX_AGE_S", _DEFAULT_MAX_AGE_S)
    now = time.time()
    removed_count = removed_bytes = 0
    with _FRAME_LOCK:
        files = []
        for path in root.glob("frame_*.png"):
            try:
                stat = path.stat()
                files.append((path, stat.st_mtime, stat.st_size))
            except OSError:
                pass
        files.sort(key=lambda item: item[1], reverse=True)
        total_bytes = sum(size for _, _, size in files)
        kept = 0
        for path, mtime, size in files:
            ref = path.stem
            if ref in keep:
                kept += 1
                continue
            if (now - mtime) > max_age_s or kept >= max_count or total_bytes > max_bytes:
                try:
                    path.unlink()
                    total_bytes -= size
                    removed_count += 1
                    removed_bytes += size
                except OSError:
                    pass
            else:
                kept += 1
    return {
        "directory": str(root),
        "removed_count": removed_count,
        "removed_bytes": removed_bytes,
        "remaining_count": len(list(root.glob("frame_*.png"))),
        "max_count": max_count,
        "max_bytes": max_bytes,
        "max_age_s": max_age_s,
    }

def take_screenshot(monitor: Optional[int] = None, region: Optional[Rect] = None,
                    max_long_edge: int = 1568, save_dir: Optional[Path] = None,
                    include_cursor: bool = False, downscale: int = 0,
                    persist: bool = True) -> Tuple[bytes, str]:
    """Capture a screenshot and optionally persist it as bounded evidence."""
    img = None
    if _HAS_MSS:
        try:
            with mss() as sct:
                if region:
                    target = {"top": region.y, "left": region.x, "width": region.w, "height": region.h}
                elif monitor is not None and monitor < len(sct.monitors):
                    target = sct.monitors[monitor]
                else:
                    target = sct.monitors[0]
                shot = sct.grab(target)
                img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        except Exception:
            img = None
    if img is None:
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab(
                bbox=(region.x, region.y, region.x + region.w, region.y + region.h),
                all_screens=True,
            ) if region else ImageGrab.grab(all_screens=True)
        except Exception:
            img = Image.new("RGB", (region.w if region else 1920, region.h if region else 1080), color=(30, 30, 30))

    target_edge = max_long_edge
    if downscale and downscale > 1:
        target_edge = max(256, int(max_long_edge / downscale))
    w, h = img.size
    if max(w, h) > target_edge:
        scale = target_edge / max(w, h)
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
    if include_cursor:
        try:
            import pyautogui
            x, y = pyautogui.position()
            ImageDraw.Draw(img).ellipse((max(0, x-5), max(0, y-5), min(img.width, x+5), min(img.height, y+5)), outline="red", width=2)
        except Exception:
            pass

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    payload = buf.getvalue()

    frame_id = f"frame_{time.time_ns()}" if persist else f"temp_{uuid.uuid4().hex[:12]}"
    if persist:
        root = get_frame_store_dir(save_dir)
        root.mkdir(parents=True, exist_ok=True)
        with _FRAME_LOCK:
            img.save(root / f"{frame_id}.png", format="PNG")
        cleanup_frame_store(root, keep_refs={frame_id})
    return payload, frame_id
