"""Master LiveRuntime orchestrator for Kratos Multimodal Live."""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Callable, Dict, Optional

from .audio import AudioManager
from .avatar import FloatingAvatar
from .bridge import KratosBridge
from .config import LiveConfig
from .events import LiveStatus, LiveStatusHub
from .narration import NarrationManager
from .router import LiveRouter
from .session import LiveSession
from .vision import VisionManager

logger = logging.getLogger(__name__)


class LiveRuntime:
    """Orchestrates audio, vision, Gemini Live session, Kratos bridge, and narration."""

    def __init__(
        self,
        config: Optional[LiveConfig] = None,
        runtime: Optional[Any] = None,
        on_user_transcript: Optional[Callable[[str], None]] = None,
        on_model_transcript: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.config = config or LiveConfig()
        self.status_hub = LiveStatusHub(
            initial_status=LiveStatus(video_mode=self.config.video_mode)
        )

        self.out_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=10)

        # Core subsystems
        self.audio = AudioManager(
            out_queue=self.out_queue,
            status_hub=self.status_hub,
            send_sample_rate=self.config.send_sample_rate,
            receive_sample_rate=self.config.receive_sample_rate,
            chunk_size=self.config.chunk_size,
            device=self.config.microphone_device,
            vad_threshold=self.config.vad_threshold,
            vad_silence_seconds=self.config.vad_silence_seconds,
        )

        self.vision = VisionManager(
            out_queue=self.out_queue,
            mode=self.config.video_mode,
            status_hub=self.status_hub,
            camera_max_size=self.config.camera_max_size,
            screen_max_size=self.config.screen_max_size,
            camera_quality=self.config.camera_jpeg_quality,
            screen_quality=self.config.screen_jpeg_quality,
            fps=self.config.video_fps,
        )

        self.bridge = KratosBridge(
            runtime=runtime,
            status_hub=self.status_hub,
        )

        # On-demand screen capture callback for LiveRouter
        async def _capture_screen() -> bytes:
            return await self.vision.capture_screen_now()

        self.router = LiveRouter(
            bridge=self.bridge,
            capture_screen_handler=_capture_screen,
        )

        self.session = LiveSession(
            config=self.config,
            out_queue=self.out_queue,
            audio_manager=self.audio,
            router=self.router,
            status_hub=self.status_hub,
            on_user_transcript=on_user_transcript,
            on_model_transcript=on_model_transcript,
        )
        self.router.set_diagnostics_handler(self.session.get_diagnostics)

        self.avatar: Optional[FloatingAvatar] = None

        # Narration sends spoken updates via the LiveSession
        def _send_narration_speech(text: str) -> None:
            if self._loop and self._loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.session.send_narration(text),
                    self._loop,
                )

        self.narration = NarrationManager(send_speech_fn=_send_narration_speech)

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._is_running = False
        self._session_task: Optional[asyncio.Task[Any]] = None

    def get_status(self) -> LiveStatus:
        return self.status_hub.get_status()

    def get_input_devices(self) -> list[Dict[str, Any]]:
        """Returns list of available microphone input devices."""
        return self.audio.get_input_devices()

    def get_active_microphone_name(self) -> str:
        """Returns the name of the currently active microphone device."""
        return self.audio.get_active_microphone_name()

    def set_microphone_device(self, device: Optional[int | str]) -> str:
        """Dynamically switches active microphone device."""
        if self._loop and self._loop.is_running() and self._is_running and self.config.is_valid():
            future = asyncio.run_coroutine_threadsafe(self.audio.set_device(device), self._loop)
            try:
                return future.result(timeout=3.0)
            except Exception as e:
                logger.warning(f"[LiveRuntime] Error switching mic device: {e}")
        self.audio.mic.device = device
        self.audio.mic.device_index, self.audio.mic.device_name = self.audio.mic._resolve_device()
        return self.audio.mic.device_name

    def mute(self) -> None:
        self.audio.mute()

    def unmute(self) -> None:
        self.audio.unmute()

    def toggle_mute(self) -> None:
        """Toggles audio input mute state."""
        if self.audio.is_muted:
            self.audio.unmute()
        else:
            self.audio.mute()

    def send_text_input_sync(self, text: str) -> None:
        """Safely dispatches text input to the LiveSession from non-async threads."""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self.session.send_text_input(text),
                self._loop,
            )

    def send_chat_turn_sync(self, text: str, timeout: float = 600.0) -> Optional[str]:
        """Sends user text to Gemini Live synchronously, waits for turn completion, and returns the spoken text."""
        if not self._loop or not self._loop.is_running() or not self.session:
            return None
        if not self.status_hub.get_status().gemini_connected:
            return None
        try:
            from kratos_agent.interfaces.cli import build_cli_input
            envelope = build_cli_input(text)
            fut = asyncio.run_coroutine_threadsafe(
                self.session.send_text_turn(envelope.text, timeout=timeout),
                self._loop,
            )
            result = fut.result(timeout=timeout + 3.0)
            if result:
                return result
            status = self.bridge.get_status()
            error = status.get("last_error")
            if error:
                return str(error.get("user_message") or error.get("message") or "Live turn completed without a model response.")
            return "Gemini Live completed the turn without returning a user-facing response."
        except Exception as e:
            logger.exception("[LiveRuntime] Error in send_chat_turn_sync")
            message = str(e).strip() or type(e).__name__
            self.status_hub.report_error("live_runtime", message)
            return f"Gemini Live turn failed: {type(e).__name__}: {message}"

    def capture_screen_now_sync(self) -> None:
        """Safely triggers an on-demand screen capture from non-async threads."""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self.vision.capture_screen_now(),
                self._loop,
            )

    def start_floating_avatar(self) -> None:
        """Launches the Windows floating assistant avatar."""
        if self.avatar is not None:
            return
        try:
            self.avatar = FloatingAvatar(
                image_path=self.config.avatar_image_path,
                status_hub=self.status_hub,
                on_text_submit=self.send_text_input_sync,
                on_screen_capture=self.capture_screen_now_sync,
                on_mute_toggle=self.toggle_mute,
                on_interrupt=self.audio.handle_interruption,
                avatar_size=self.config.avatar_size,
            )
            self.avatar.start()
        except Exception as e:
            logger.warning(f"[LiveRuntime] Failed to start floating avatar: {e}")

    def stop_floating_avatar(self) -> None:
        """Stops the floating assistant avatar."""
        if self.avatar:
            try:
                self.avatar.stop()
            except Exception:
                pass
            self.avatar = None

    async def set_vision_mode(self, mode: str) -> Dict[str, Any]:
        return await self.vision.set_mode(mode)


    async def start(self) -> None:
        """Starts all Live subsystems within the current asyncio event loop."""
        if self._is_running:
            return

        self._loop = asyncio.get_running_loop()
        self._is_running = True
        if not self.config.is_valid():
            if not self.config.enabled:
                err = "Gemini Live is disabled by KRATOS_LIVE_ENABLED."
            else:
                err = "Gemini Live needs GEMINI_API_KEY or GOOGLE_API_KEY before audio can stream."
            logger.warning(f"[LiveRuntime] {err}")
            self.status_hub.report_error("gemini", err)
            return

        logger.info("[LiveRuntime] Starting audio and vision subsystems...")
        await self.audio.start()
        await self.vision.start()
        self.narration.start()

        if self.config.floating_avatar_enabled:
            self.start_floating_avatar()

        self._session_task = asyncio.create_task(
            self.session.run_connection_loop(),
            name="kratos-live-session-loop",
        )
        logger.info("[LiveRuntime] Multimodal Live subsystems running.")

    async def stop(self) -> None:
        """Stops all Live subsystems cleanly."""
        if not self._is_running:
            return
        self._is_running = False

        logger.info("[LiveRuntime] Stopping Live subsystems...")
        self.stop_floating_avatar()
        self.narration.stop()

        if self._session_task and not self._session_task.done():
            self._session_task.cancel()
        await self.session.stop()
        await self.vision.stop()
        await self.audio.stop()

        logger.info("[LiveRuntime] Live subsystems stopped.")

    def start_in_background(self) -> None:
        """Launches the LiveRuntime in a dedicated background daemon thread."""
        if self._thread and self._thread.is_alive():
            return

        def _worker() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            try:
                loop.run_until_complete(self.start())
                if not self._is_running:
                    return
                loop.run_forever()
            except Exception as e:
                logger.warning(f"[LiveRuntime] Background thread error: {e}")
            finally:
                try:
                    loop.run_until_complete(self.stop())
                except Exception:
                    pass
                loop.close()

        self._thread = threading.Thread(
            target=_worker,
            daemon=True,
            name="kratos-live-runtime",
        )
        self._thread.start()
        logger.info("[LiveRuntime] Started in background daemon thread.")

    def stop_background(self) -> None:
        """Signals the background LiveRuntime thread to stop."""
        loop = self._loop
        thread = self._thread
        if loop and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self.stop(), loop)
            try:
                future.result(timeout=5.0)
            except Exception:
                pass
            loop.call_soon_threadsafe(loop.stop)
        if thread and thread is not threading.current_thread():
            thread.join(timeout=5.0)
            if not thread.is_alive():
                self._thread = None
                self._loop = None


# Global runtime instance
_global_live_runtime: Optional[LiveRuntime] = None


def get_live_runtime() -> LiveRuntime:
    global _global_live_runtime
    if _global_live_runtime is None:
        _global_live_runtime = LiveRuntime()
    return _global_live_runtime
