"""Master LiveRuntime orchestrator for Kratos Multimodal Live."""
from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from typing import Any

from .audio import AudioManager
from .config import LiveConfig
from .events import LiveState, LiveStatus, LiveStatusHub
from .session import LiveSession
from .vision import VisionManager

logger = logging.getLogger(__name__)


class LiveRuntime:
    """Orchestrates local speech recognition, optional Gemini TTS, and vision capture."""

    def __init__(
        self,
        config: LiveConfig | None = None,
        runtime: Any | None = None,
        on_user_transcript: Callable[[str], None] | None = None,
        on_model_transcript: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config or LiveConfig()
        self.status_hub = LiveStatusHub(
            initial_status=LiveStatus(video_mode=self.config.video_mode)
        )

        self.out_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=10)

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

        self.session = LiveSession(
            config=self.config,
            out_queue=self.out_queue,
            audio_manager=self.audio,
            status_hub=self.status_hub,
            on_model_transcript=on_model_transcript,
        )

        self.on_user_transcript = on_user_transcript
        self.on_model_transcript = on_model_transcript
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._is_running = False
        self._session_task: asyncio.Task[Any] | None = None

    def get_status(self) -> LiveStatus:
        return self.status_hub.get_status()

    def get_input_devices(self) -> list[dict[str, Any]]:
        """Returns list of available microphone input devices."""
        return self.audio.get_input_devices()

    def get_active_microphone_name(self) -> str:
        """Returns the name of the currently active microphone device."""
        return self.audio.get_active_microphone_name()

    def set_microphone_device(self, device: int | str | None) -> str:
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
        listener = getattr(self, "native_hearing", None)
        if listener:
            listener.mute()

    def unmute(self) -> None:
        self.audio.unmute()
        listener = getattr(self, "native_hearing", None)
        if listener:
            listener.unmute()

    def speak_marked(self, text: str) -> None:
        """Speak a phrase extracted from a valid ``[[speak]]`` directive."""
        if not text or not text.strip():
            return
        if self.config.is_gemini_backend and self._loop and self._loop.is_running() and self.session and self.status_hub.get_status().gemini_connected:
            asyncio.run_coroutine_threadsafe(
                self.session.speak_text(text),
                self._loop,
            )
        else:
            try:
                from kratos_agent.output.native_voice import get_native_voice
                get_native_voice().speak(text)
            except Exception as e:
                logger.debug("[LiveRuntime] Fallback voice error: %s", e)

    def speak(self, text: str) -> None:
        """Speak only text enclosed by the explicit model speech directive."""
        from kratos_agent.output.speech_directives import extract_speech_directives

        directive = extract_speech_directives(text)
        if directive.valid and directive.speech_text:
            self.speak_marked(directive.speech_text)

    async def set_vision_mode(self, mode: str) -> dict[str, Any]:
        normalized = "none" if mode.lower().strip() == "off" else mode.lower().strip()
        if normalized not in ("camera", "screen", "both", "none"):
            raise ValueError("Unsupported vision mode: choose camera, screen, both, or off.")
        self.vision.mode = normalized
        self.status_hub.update(video_mode=normalized, camera_active=False, screen_active=False)
        return self.vision.get_capture_status()


    async def start(self) -> None:
        """Starts all Live subsystems within the current asyncio event loop."""
        if self._is_running:
            return

        self._loop = asyncio.get_running_loop()
        self._is_running = True
        if not self.config.enabled:
            err = "Live speech is disabled by KRATOS_LIVE_ENABLED."
            logger.info("[LiveRuntime] %s", err)
            self.status_hub.report_error("live_speech", err)
            return

        logger.info("[LiveRuntime] Starting local speech recognition and speaker output...")
        if self.config.is_gemini_backend:
            await self.audio.start_output_only()

        try:
            from .native_listener import get_native_hearing

            def _on_heard(text: str) -> None:
                if self.on_user_transcript:
                    try:
                        self.on_user_transcript(text)
                    except Exception:
                        logger.exception("[LiveRuntime] Kratos voice-input handler failed")

            self.native_hearing = get_native_hearing(on_transcription=_on_heard)
            self.native_hearing.start()
            self.status_hub.update(microphone_active=True, microphone_health="online")
        except Exception as exc:
            logger.warning("[LiveRuntime] Local speech recognition unavailable: %s", exc)
            self.status_hub.report_error("speech_recognition", str(exc) or type(exc).__name__)

        if self.config.is_gemini_backend:
            self._session_task = asyncio.create_task(
                self.session.run_connection_loop(),
                name="kratos-live-session-loop",
            )
            logger.info("[LiveRuntime] Gemini speech-output session running; Kratos remains the only agent.")
        else:
            self.status_hub.update(
                gemini_connected=False,
                live_health="native",
                current_state=LiveState.IDLE,
            )
            logger.info("[LiveRuntime] Native TTS fallback and local speech recognition running.")

    async def stop(self) -> None:
        """Stops all Live subsystems cleanly."""
        if not self._is_running:
            return
        self._is_running = False

        logger.info("[LiveRuntime] Stopping Live subsystems...")
        if hasattr(self, "native_hearing") and self.native_hearing:
            try:
                self.native_hearing.stop()
            except Exception:
                pass

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
                except Exception as exc:
                    logger.debug("Operation error suppressed: %s", exc)
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
        if loop and not loop.is_closed() and loop.is_running():
            coroutine = self.stop()
            try:
                future = asyncio.run_coroutine_threadsafe(coroutine, loop)
            except RuntimeError:
                coroutine.close()
                if not loop.is_closed():
                    raise
            else:
                try:
                    future.result(timeout=5.0)
                except Exception as exc:
                    logger.debug("Operation error suppressed: %s", exc)
            try:
                loop.call_soon_threadsafe(loop.stop)
            except RuntimeError:
                # The background worker can finish and close its loop while
                # the foreground is waiting for shutdown. Exit is idempotent.
                if not loop.is_closed():
                    raise
        if thread and thread is not threading.current_thread():
            thread.join(timeout=5.0)
            if not thread.is_alive():
                self._thread = None
                self._loop = None


# Global runtime instance
_global_live_runtime: LiveRuntime | None = None


def get_live_runtime() -> LiveRuntime:
    global _global_live_runtime
    if _global_live_runtime is None:
        _global_live_runtime = LiveRuntime()
    return _global_live_runtime
