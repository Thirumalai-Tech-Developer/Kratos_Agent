"""Vision manager for Kratos Multimodal Live."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from .camera import CameraCapture
from .events import LiveStatusHub
from .screen import ScreenCapture

logger = logging.getLogger(__name__)


class VisionManager:
    """Manages camera and screen capture according to mode (camera, screen, both, none)."""

    def __init__(
        self,
        out_queue: asyncio.Queue[Dict[str, Any]],
        mode: str = "camera",
        status_hub: Optional[LiveStatusHub] = None,
        camera_max_size: tuple[int, int] = (1024, 1024),
        screen_max_size: tuple[int, int] = (1920, 1080),
        camera_quality: int = 85,
        screen_quality: int = 80,
        fps: float = 1.0,
    ) -> None:
        self.out_queue = out_queue
        self.mode = mode.lower()
        self.status_hub = status_hub
        self.fps = fps

        self.camera = CameraCapture(
            out_queue=self.out_queue,
            max_size=camera_max_size,
            jpeg_quality=camera_quality,
            fps=fps,
        )
        self.screen = ScreenCapture(
            out_queue=self.out_queue,
            max_size=screen_max_size,
            jpeg_quality=screen_quality,
            fps=fps,
        )
        self._tasks: List[asyncio.Task[Any]] = []

    async def start(self) -> None:
        """Start vision capture tasks based on active mode."""
        await self.stop()
        self._tasks.clear()

        if self.mode in ("camera", "both"):
            async def _run_camera():
                await self.camera.run()
                if self.status_hub:
                    self.status_hub.update(camera_active=self.camera.is_running)

            t_cam = asyncio.create_task(_run_camera(), name="kratos-live-camera")
            self._tasks.append(t_cam)

        if self.mode in ("screen", "both"):
            async def _run_screen():
                await self.screen.run()
                if self.status_hub:
                    self.status_hub.update(screen_active=self.screen.is_running)

            t_scr = asyncio.create_task(_run_screen(), name="kratos-live-screen")
            self._tasks.append(t_scr)

        await asyncio.sleep(0.05)
        if self.status_hub:
            self.status_hub.update(
                camera_active=self.camera.is_running,
                screen_active=self.screen.is_running,
                video_mode=self.mode,
            )

    async def stop(self) -> None:
        """Stop all active vision capture tasks."""
        self.camera.stop()
        self.screen.stop()
        for t in self._tasks:
            if not t.done():
                t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        if self.status_hub:
            self.status_hub.update(camera_active=False, screen_active=False)

    async def set_mode(self, mode: str) -> None:
        """Dynamically switch vision mode (camera, screen, both, none)."""
        mode = mode.lower().strip()
        if mode not in ("camera", "screen", "both", "none"):
            raise ValueError(f"Unsupported vision mode: {mode}. Choices: camera, screen, both, none.")
        self.mode = mode
        await self.start()

    async def capture_screen_now(self) -> Optional[Dict[str, Any]]:
        """Trigger an on-demand screen capture immediately and send to Gemini."""
        return await self.screen.capture_now_and_queue()

    async def capture_camera_now(self) -> Optional[Dict[str, Any]]:
        """Trigger an on-demand camera capture immediately and send to Gemini."""
        return await self.camera.capture_now_and_queue()

    async def capture_vision_now(self, preferred_source: str = "screen") -> Optional[Dict[str, Any]]:
        """Captures either screen or camera based on active mode or preference."""
        if preferred_source == "camera" or self.mode == "camera":
            return await self.capture_camera_now()
        return await self.capture_screen_now()
