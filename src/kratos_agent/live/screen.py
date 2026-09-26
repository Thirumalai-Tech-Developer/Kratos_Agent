"""Screen capture and health verification for Kratos Multimodal Live (§6, §7, §8, §9, §10, §11, §15)."""
from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from PIL import Image

from kratos_agent.core.error_pipeline import get_error_pipeline
from kratos_agent.core.errors import create_kratos_error

logger = logging.getLogger(__name__)


class ComponentHealth(str, Enum):
    OFFLINE = "offline"
    STARTING = "starting"
    ONLINE = "online"
    DEGRADED = "degraded"
    ERROR = "error"


@dataclass
class CaptureHealth:
    available: bool
    backend: str | None
    width: int
    height: int
    frame_count: int
    last_frame_time: float | None
    error: str | None


@dataclass
class ScreenFrame:
    timestamp: float
    width: int
    height: int
    jpeg: bytes
    monitor: int
    backend: str

    @property
    def frame_hash(self) -> str:
        return hashlib.sha256(self.jpeg).hexdigest()[:16]


class VisionFrameCache:
    """Thread-safe cache holding the most recent screen frame with expiry threshold (§15)."""

    def __init__(self, threshold_seconds: float = 1.5) -> None:
        self.threshold = threshold_seconds
        self._latest_frame: ScreenFrame | None = None

    def get(self) -> ScreenFrame | None:
        if self._latest_frame is None:
            return None
        age = time.time() - self._latest_frame.timestamp
        if age <= self.threshold:
            return self._latest_frame
        return None

    def put(self, frame: ScreenFrame) -> None:
        self._latest_frame = frame

    def clear(self) -> None:
        self._latest_frame = None


_global_frame_cache = VisionFrameCache()


def get_vision_frame_cache() -> VisionFrameCache:
    return _global_frame_cache


class ScreenCapture:
    """Captures monitor screenshots via mss, compresses to JPEG, and queues for Gemini Live."""

    def __init__(
        self,
        out_queue: asyncio.Queue[dict[str, Any]],
        max_size: tuple[int, int] = (1920, 1080),
        jpeg_quality: int = 80,
        fps: float = 1.0,
        monitor_index: int = 1,
    ) -> None:
        self.out_queue = out_queue
        self.max_size = max_size
        self.jpeg_quality = jpeg_quality
        self.fps = fps
        self.monitor_index = monitor_index
        self.is_running = False

        self.health_status = ComponentHealth.OFFLINE
        self.frame_count = 0
        self.last_frame_time: float | None = None
        self.last_error: str | None = None
        self.frame_cache = get_vision_frame_cache()

    def _select_monitor(self, sct: Any) -> tuple[int, dict[str, int]]:
        """Safely selects monitor dictionary from mss, handling multi-monitor and single-monitor setups (§10)."""
        monitors = sct.monitors
        if not monitors:
            raise RuntimeError("No displays detected by mss.")

        # On Windows: monitors[0] is virtual all-in-one; monitors[1] is primary monitor
        # If requested monitor_index is valid, use it; otherwise fallback to primary (1) or virtual (0)
        idx = self.monitor_index
        if idx < len(monitors) and idx >= 0:
            return idx, monitors[idx]
        elif len(monitors) > 1:
            return 1, monitors[1]
        return 0, monitors[0]

    def _capture_screen_frame(self) -> ScreenFrame:
        """Captures a ScreenFrame directly without queueing."""
        import mss

        with mss.mss() as sct:
            actual_idx, monitor = self._select_monitor(sct)
            screenshot = sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
            orig_w, orig_h = img.size

            if orig_w > self.max_size[0] or orig_h > self.max_size[1]:
                img.thumbnail(self.max_size)

            buffer = io.BytesIO()
            img.save(buffer, format="jpeg", quality=self.jpeg_quality)
            jpeg_bytes = buffer.getvalue()

            frame = ScreenFrame(
                timestamp=time.time(),
                width=img.size[0],
                height=img.size[1],
                jpeg=jpeg_bytes,
                monitor=actual_idx,
                backend="mss",
            )
            self.frame_cache.put(frame)
            self.frame_count += 1
            self.last_frame_time = frame.timestamp
            self.last_error = None
            self.health_status = ComponentHealth.ONLINE
            return frame

    def capture_now(self) -> ScreenFrame | None:
        """Captures a single screenshot on demand immediately, returning ScreenFrame."""
        # 1. Check cache first (§15)
        cached = self.frame_cache.get()
        if cached is not None:
            return cached

        # 2. Local capture
        try:
            return self._capture_screen_frame()
        except Exception as e:
            self.last_error = str(e)
            self.health_status = ComponentHealth.ERROR
            err = create_kratos_error(
                e,
                subsystem="screen",
                operation="capture_now",
                details={"monitor": self.monitor_index, "backend": "mss"},
            )
            get_error_pipeline().record_error(err)
            logger.warning(f"[Screen] Screen capture error: {e}")
            return None

    def health_check(self) -> CaptureHealth:
        """Tests local screen capture, validates dimensions and JPEG payload (§7, §9)."""
        try:
            import mss
        except ImportError:
            self.health_status = ComponentHealth.ERROR
            self.last_error = "mss is not installed"
            return CaptureHealth(
                available=False,
                backend=None,
                width=0,
                height=0,
                frame_count=self.frame_count,
                last_frame_time=self.last_frame_time,
                error=self.last_error,
            )

        try:
            frame = self._capture_screen_frame()
            if not frame.jpeg or len(frame.jpeg) < 100:
                raise ValueError("Captured JPEG frame is empty or corrupted.")
            if frame.width <= 0 or frame.height <= 0:
                raise ValueError(f"Invalid frame dimensions: {frame.width}x{frame.height}")

            self.health_status = ComponentHealth.ONLINE
            return CaptureHealth(
                available=True,
                backend="mss",
                width=frame.width,
                height=frame.height,
                frame_count=self.frame_count,
                last_frame_time=frame.timestamp,
                error=None,
            )
        except Exception as e:
            self.health_status = ComponentHealth.ERROR
            self.last_error = str(e)
            err = create_kratos_error(
                e,
                subsystem="screen",
                operation="health_check",
                details={"monitor": self.monitor_index},
            )
            get_error_pipeline().record_error(err)
            return CaptureHealth(
                available=False,
                backend="mss",
                width=0,
                height=0,
                frame_count=self.frame_count,
                last_frame_time=self.last_frame_time,
                error=str(e),
            )

    async def capture_now_and_queue(self) -> ScreenFrame | None:
        """Captures a screenshot on demand, enqueues JPEG for Gemini Live, and returns ScreenFrame."""
        frame = await asyncio.to_thread(self.capture_now)
        if frame is not None:
            payload = {
                "mime_type": "image/jpeg",
                "data": frame.jpeg,
            }
            try:
                self.out_queue.put_nowait(payload)
            except asyncio.QueueFull:
                try:
                    self.out_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                self.out_queue.put_nowait(payload)
            logger.info(f"[Screen] Enqueued {frame.width}x{frame.height} frame for Gemini Live.")
        return frame

    async def run(self) -> None:
        """Runs the screen frame capture loop continuously."""
        # 1. Local-first health check (§7, §9)
        health = await asyncio.to_thread(self.health_check)
        if not health.available:
            logger.warning(f"[Screen] Screen capture health check failed: {health.error}. Screen offline.")
            self.is_running = False
            return

        self.is_running = True
        interval = 1.0 / max(0.1, self.fps)
        logger.info(f"[Screen] Screen capture started ({health.width}x{health.height}, {self.fps} fps).")

        try:
            while self.is_running:
                frame = await asyncio.to_thread(self.capture_now)
                if frame is None:
                    await asyncio.sleep(interval)
                    continue

                payload = {
                    "mime_type": "image/jpeg",
                    "data": frame.jpeg,
                }
                try:
                    self.out_queue.put_nowait(payload)
                except asyncio.QueueFull:
                    try:
                        self.out_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    try:
                        self.out_queue.put_nowait(payload)
                    except asyncio.QueueFull:
                        pass

                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.last_error = str(e)
            self.health_status = ComponentHealth.ERROR
            logger.warning(f"[Screen] Capture loop error: {e}")
        finally:
            self.is_running = False
            self.health_status = ComponentHealth.OFFLINE
            logger.info("[Screen] Screen capture stopped.")

    def stop(self) -> None:
        self.is_running = False
        self.health_status = ComponentHealth.OFFLINE


ScreenCaptureStream = ScreenCapture
_global_screen_stream: ScreenCapture | None = None


def get_screen_stream(out_queue: asyncio.Queue[dict[str, Any]] | None = None) -> ScreenCapture:
    """Returns singleton ScreenCapture / ScreenCaptureStream instance (§6, §7)."""
    global _global_screen_stream
    if _global_screen_stream is None:
        import asyncio
        q = out_queue if out_queue is not None else asyncio.Queue()
        _global_screen_stream = ScreenCapture(out_queue=q)
    return _global_screen_stream

