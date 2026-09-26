"""Vision coordinator for Kratos Multimodal Live (§6, §12, §13, §14, §15, §16, §40)."""
from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

from .camera import CameraCapture
from .events import LiveStatusHub
from .screen import (
    CaptureHealth,
    ScreenCapture,
    ScreenFrame,
)

logger = logging.getLogger(__name__)


class VisionManager:
    """Manages camera and screen capture according to mode (camera, screen, both, none)."""

    def __init__(
        self,
        out_queue: asyncio.Queue[dict[str, Any]],
        mode: str = "camera",
        status_hub: LiveStatusHub | None = None,
        camera_max_size: tuple[int, int] = (1024, 1024),
        screen_max_size: tuple[int, int] = (1920, 1080),
        camera_quality: int = 85,
        screen_quality: int = 80,
        fps: float = 1.0,
    ) -> None:
        self.out_queue = out_queue
        self.mode = mode.lower()
        self.status_hub = status_hub
        # Gemini Live accepts video at up to one frame per second.
        self.fps = min(1.0, max(0.1, float(fps)))

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
        self._tasks: list[asyncio.Task[Any]] = []

    def check_screen_health(self) -> CaptureHealth:
        """Performs a synchronous local screen capture health check."""
        return self.screen.health_check()

    def get_capture_status(self) -> dict[str, Any]:
        """Returns structured capture status for CLI and UI (§13)."""
        health = self.screen.health_check()
        gemini_connected = (
            self.status_hub.status.gemini_connected if self.status_hub else False
        )
        return {
            "mode": self.mode.upper(),
            "capture_online": health.available,
            "backend": health.backend or "MSS",
            "resolution": f"{health.width}x{health.height}" if health.available else "0x0",
            "gemini_stream": "CONNECTED" if gemini_connected else "OFFLINE",
            "error": health.error,
        }

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
            # Health check before marking online (§7, §8)
            health = await asyncio.to_thread(self.screen.health_check)
            if health.available:
                async def _run_screen():
                    await self.screen.run()
                    if self.status_hub:
                        self.status_hub.update(screen_active=self.screen.is_running)

                t_scr = asyncio.create_task(_run_screen(), name="kratos-live-screen")
                self._tasks.append(t_scr)
            else:
                logger.warning(f"[VisionManager] Screen capture offline: {health.error}")
                if self.status_hub:
                    self.status_hub.update(screen_active=False, screen_health="error")
                    self.status_hub.report_error("screen", f"Screen capture unavailable: {health.error}")

        await asyncio.sleep(0.05)
        if self.status_hub:
            self.status_hub.update(
                camera_active=self.camera.is_running,
                screen_active=self.screen.is_running,
                camera_health="online" if self.camera.is_running else "offline",
                screen_health="online" if self.screen.is_running else "offline",
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

    async def set_mode(self, mode: str) -> dict[str, Any]:
        """Dynamically switch vision mode and return health status (§12, §13)."""
        mode = mode.lower().strip()
        if mode not in ("camera", "screen", "both", "none", "off"):
            raise ValueError(f"Unsupported vision mode: {mode}. Choices: camera, screen, both, off, none.")
        if mode == "off":
            mode = "none"
        self.mode = mode
        await self.start()
        return self.get_capture_status()

    async def capture_screen_now(self) -> ScreenFrame | None:
        """Trigger an on-demand screen capture immediately and return ScreenFrame."""
        return await self.screen.capture_now_and_queue()

    async def capture_camera_now(self) -> dict[str, Any] | None:
        """Trigger an on-demand camera capture immediately and send to Gemini."""
        return await self.camera.capture_now_and_queue()

    async def capture_vision_now(self, preferred_source: str = "screen") -> Any | None:
        """Captures either screen or camera based on active mode or preference."""
        if preferred_source == "camera" or self.mode == "camera":
            return await self.capture_camera_now()
        return await self.capture_screen_now()

    async def describe_screen_fallback(self, prompt: str = "Describe what you see on the screen in detail.") -> str:
        """Local vision fallback when Gemini Live stream is unavailable (§16, §40)."""
        frame = self.screen.capture_now()
        if not frame:
            return "Screen capture failed. Unable to capture desktop frame."

        # Try Brain vision endpoint via OmniRoute / OpenAI-compatible payload
        try:
            from kratos_agent.brain.client import BrainClient
            from kratos_agent.brain.config import load_brain_config

            b64_img = base64.b64encode(frame.jpeg).decode("utf-8")
            cfg = load_brain_config()
            client = BrainClient(cfg)

            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"},
                        },
                    ],
                }
            ]
            response = await client.send_chat(messages, stream=False)
            return response.get("content", "No description returned from model.")
        except Exception as e:
            logger.warning(f"[VisionManager] Fallback vision description error: {e}")
            return f"Captured {frame.width}x{frame.height} screen frame (hash: {frame.frame_hash}), but vision model analysis failed: {e}"
