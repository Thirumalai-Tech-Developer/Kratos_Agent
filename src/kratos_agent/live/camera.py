"""Camera video capture for Kratos Multimodal Live."""
from __future__ import annotations

import asyncio
import io
import logging
from typing import Any, Dict, Optional
from PIL import Image

logger = logging.getLogger(__name__)


class CameraCapture:
    """Captures camera frames via OpenCV, compresses to JPEG, and queues for Gemini Live."""

    def __init__(
        self,
        out_queue: asyncio.Queue[Dict[str, Any]],
        device_index: int = 0,
        max_size: tuple[int, int] = (1024, 1024),
        jpeg_quality: int = 85,
        fps: float = 1.0,
    ) -> None:
        self.out_queue = out_queue
        self.device_index = device_index
        self.max_size = max_size
        self.jpeg_quality = jpeg_quality
        self.fps = fps
        self.is_running = False
        self._cap: Any = None

    def _capture_frame(self, cap: Any) -> Optional[Dict[str, Any]]:
        ret, frame = cap.read()
        if not ret or frame is None:
            return None

        import cv2

        # BGR to RGB
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(frame_rgb)
        img.thumbnail(self.max_size)

        buffer = io.BytesIO()
        img.save(buffer, format="jpeg", quality=self.jpeg_quality)
        buffer.seek(0)

        return {
            "mime_type": "image/jpeg",
            "data": buffer.read(),
        }

    async def capture_now_and_queue(self) -> Optional[Dict[str, Any]]:
        """Captures a camera frame on demand and enqueues it for Gemini Live."""
        try:
            import cv2
            cap = self._cap
            temp_cap = False
            if cap is None or not cap.isOpened():
                cap = await asyncio.to_thread(cv2.VideoCapture, self.device_index)
                temp_cap = True
            if not cap.isOpened():
                return None
            frame = await asyncio.to_thread(self._capture_frame, cap)
            if temp_cap:
                cap.release()
            if frame is not None:
                try:
                    self.out_queue.put_nowait(frame)
                except asyncio.QueueFull:
                    try:
                        self.out_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    self.out_queue.put_nowait(frame)
                logger.info("[Camera] Captured on-demand camera frame and enqueued for Gemini Live.")
            return frame
        except Exception as e:
            logger.warning(f"[Camera] On-demand capture error: {e}")
            return None

    async def run(self) -> None:
        """Runs the camera frame capture loop."""
        try:
            import cv2
        except ImportError:
            logger.warning("[Camera] OpenCV (cv2) is not installed. Camera offline.")
            self.is_running = False
            return

        logger.info(f"[Camera] Opening camera device {self.device_index}...")
        try:
            self._cap = await asyncio.to_thread(cv2.VideoCapture, self.device_index)
            if not self._cap.isOpened():
                logger.warning(f"[Camera] Could not open camera device {self.device_index}.")
                self.is_running = False
                return
        except Exception as e:
            logger.warning(f"[Camera] Failed to initialize camera: {e}")
            self.is_running = False
            return

        self.is_running = True
        interval = 1.0 / max(0.1, self.fps)

        try:
            while self.is_running:
                frame = await asyncio.to_thread(self._capture_frame, self._cap)
                if frame is None:
                    logger.debug("[Camera] Failed to capture frame from camera.")
                    await asyncio.sleep(interval)
                    continue

                try:
                    self.out_queue.put_nowait(frame)
                except asyncio.QueueFull:
                    try:
                        self.out_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    try:
                        self.out_queue.put_nowait(frame)
                    except asyncio.QueueFull:
                        pass

                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass
        except RuntimeError as e:
            if "cannot schedule new futures after shutdown" not in str(e):
                logger.warning(f"[Camera] Capture loop error: {e}")
        except Exception as e:
            logger.warning(f"[Camera] Capture loop error: {e}")
        finally:
            self.is_running = False
            if self._cap is not None:
                try:
                    self._cap.release()
                except Exception:
                    pass
                self._cap = None
            logger.info("[Camera] Camera released.")

    def stop(self) -> None:
        self.is_running = False
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
