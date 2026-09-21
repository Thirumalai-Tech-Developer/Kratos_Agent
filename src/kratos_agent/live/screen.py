"""Screen capture for Kratos Multimodal Live."""
from __future__ import annotations

import asyncio
import io
import logging
from typing import Any, Dict, Optional
from PIL import Image

logger = logging.getLogger(__name__)


class ScreenCapture:
    """Captures primary monitor screenshots via mss, compresses to JPEG, and queues for Gemini Live."""

    def __init__(
        self,
        out_queue: asyncio.Queue[Dict[str, Any]],
        max_size: tuple[int, int] = (1920, 1080),
        jpeg_quality: int = 80,
        fps: float = 1.0,
    ) -> None:
        self.out_queue = out_queue
        self.max_size = max_size
        self.jpeg_quality = jpeg_quality
        self.fps = fps
        self.is_running = False

    def _capture_screen(self) -> Optional[Dict[str, Any]]:
        import mss

        try:
            with mss.mss() as sct:
                monitor = sct.monitors[0]
                screenshot = sct.grab(monitor)
                img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
                img.thumbnail(self.max_size)

                buffer = io.BytesIO()
                img.save(buffer, format="jpeg", quality=self.jpeg_quality)
                buffer.seek(0)

                return {
                    "mime_type": "image/jpeg",
                    "data": buffer.read(),
                }
        except Exception as e:
            logger.warning(f"[Screen] Screen capture grab error: {e}")
            return None

    def capture_now(self) -> Optional[Dict[str, Any]]:
        """Captures a single screenshot on demand immediately."""
        return self._capture_screen()

    async def capture_now_and_queue(self) -> Optional[Dict[str, Any]]:
        """Captures a screenshot on demand and enqueues it for Gemini Live."""
        frame = await asyncio.to_thread(self._capture_screen)
        if frame is not None:
            try:
                self.out_queue.put_nowait(frame)
            except asyncio.QueueFull:
                try:
                    self.out_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                self.out_queue.put_nowait(frame)
            logger.info("[Screen] Captured on-demand screenshot and enqueued for Gemini Live.")
        return frame

    async def run(self) -> None:
        """Runs the screen frame capture loop."""
        try:
            import mss
        except ImportError:
            logger.warning("[Screen] mss is not installed. Screen capture offline.")
            self.is_running = False
            return

        self.is_running = True
        interval = 1.0 / max(0.1, self.fps)
        logger.info("[Screen] Screen capture started.")

        try:
            while self.is_running:
                frame = await asyncio.to_thread(self._capture_screen)
                if frame is None:
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
                logger.warning(f"[Screen] Capture loop error: {e}")
        except Exception as e:
            logger.warning(f"[Screen] Capture loop error: {e}")
        finally:
            self.is_running = False
            logger.info("[Screen] Screen capture stopped.")

    def stop(self) -> None:
        self.is_running = False
