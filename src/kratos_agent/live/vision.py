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
        """Local vision analysis using OmniRoute vision models without Gemini Live."""
        return await self.analyze_vision(prompt=prompt, source="screen")

    async def analyze_vision(self, prompt: str = "Describe what you see in detail.", source: str = "screen") -> str:
        """Captures screen or camera frame and analyzes it using the active/best OmniRoute vision model."""
        jpeg_bytes = None
        width = 0
        height = 0
        if source == "camera" or self.mode == "camera":
            cam_data = await self.capture_camera_now()
            if cam_data and "data" in cam_data:
                jpeg_bytes = cam_data["data"]
                width, height = cam_data.get("width", 0), cam_data.get("height", 0)
        else:
            frame = self.screen.capture_now()
            if frame:
                jpeg_bytes = frame.jpeg
                width, height = frame.width, frame.height

        if not jpeg_bytes:
            return f"{source.capitalize()} capture failed. Unable to capture visual frame."

        try:
            from kratos_agent.brain.client import BrainClient
            from kratos_agent.brain.config import get_default_model, is_vision_model, get_vision_models

            # Determine vision model
            active_model = get_default_model()
            if is_vision_model(active_model):
                target_model = active_model
            else:
                # If active model is text-only (e.g. ds-web/deepseek-v4-pro), choose an OmniRoute vision model
                vision_models = get_vision_models()
                target_model = vision_models[0] if vision_models else "antigravity/gemini-3.7-flash-high"

            b64_img = base64.b64encode(jpeg_bytes).decode("utf-8")
            client = BrainClient()

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
            text, _ = await asyncio.to_thread(
                client.complete,
                target_model,
                messages,
                timeout=45.0,
                stream=True,
            )
            return text or f"Vision model {target_model} returned empty response."
        except Exception as e:
            logger.warning(f"[VisionManager] Vision model analysis error: {e}")
            return f"Captured {width}x{height} frame, but vision analysis failed: {e}"
