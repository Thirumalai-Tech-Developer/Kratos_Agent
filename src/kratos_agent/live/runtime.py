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
        self._speech_started = False
        self._hearing_started = False
        self._resource_loop: asyncio.AbstractEventLoop | None = None
        self._startup_lock = asyncio.Lock()
        self._lifecycle_lock = threading.RLock()
        self._ready = threading.Event()
        self._start_error: str | None = None
        self._requested_speech = False
        self._requested_hearing = False

    def get_status(self) -> LiveStatus:
        # Camera opening may finish after set_mode returns. Poll real local
        # capture flags without acquiring a frame or opening any device.
        status = self.status_hub.get_status()
        with self._lifecycle_lock:
            listener = getattr(self, "native_hearing", None)
            if listener is not None and hasattr(listener, "is_running"):
                if self._hearing_started and not listener.is_running:
                    self._hearing_started = False
                    if "speech_recognition" not in status.errors:
                        self.status_hub.report_error(
                            "speech_recognition",
                            "Local speech recognition stopped. Click Unmute to retry; check Windows microphone permissions and the speech language.",
                        )
                microphone_active = bool(self._hearing_started and listener.is_running)
                microphone_health = ("muted" if status.muted else "online") if microphone_active else (
                    "error" if "speech_recognition" in status.errors else "offline"
                )
                if status.microphone_active != microphone_active or status.microphone_health != microphone_health:
                    self.status_hub.update(microphone_active=microphone_active, microphone_health=microphone_health)
        camera_active = self.vision.mode in ("camera", "both") and self.vision.camera.is_running
        screen_active = self.vision.mode in ("screen", "both") and self.vision.screen.is_running
        observed = {
            "camera_active": bool(camera_active), "screen_active": bool(screen_active),
            "camera_health": "online" if camera_active else ("error" if "camera" in status.errors else "offline"),
            "screen_health": "online" if screen_active else ("error" if "screen" in status.errors else "offline"),
        }
        if any(getattr(status, name) != value for name, value in observed.items()):
            self.status_hub.update(**observed)
        return status

    def runtime_status(self) -> dict[str, Any]:
        """Report local lifecycle separately from Gemini's speech connection."""
        running = bool(self._loop and self._loop.is_running() and self._is_running)
        return {"runtime_started": running, "control_loop_running": running,
                "speech_started": self._speech_started, "hearing_started": self._hearing_started,
                "start_error": self._start_error, "backend": self.config.backend,
                "model": self.config.model, "config_enabled": self.config.enabled}

    def ensure_control_loop(self, timeout: float = 5.0) -> dict[str, Any]:
        """Start this profile's capture-control loop without speech or hearing."""
        self.start_in_background(start_hearing=False, control_only=True)
        if not self._ready.wait(timeout=max(0.0, timeout)):
            raise TimeoutError("Live control runtime did not become ready; retry once it finishes starting.")
        if not self._loop or not self._loop.is_running() or not self._is_running:
            raise RuntimeError(self._start_error or "Live control runtime could not start.")
        return self.runtime_status()

    def _bind_loop_resources(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._resource_loop is not None and self._resource_loop is not loop:
            # Queue waiters and contended locks retain their original event loop.
            # Reconnect creates a new daemon loop, so replace these shared refs.
            self.out_queue = asyncio.Queue(maxsize=10)
            self.audio.out_queue = self.out_queue
            self.audio.mic.out_queue = self.out_queue
            self.vision.out_queue = self.out_queue
            self.vision.camera.out_queue = self.out_queue
            self.vision.screen.out_queue = self.out_queue
            self.session.out_queue = self.out_queue
            self.audio.audio_in_queue = asyncio.Queue()
            self.audio.speaker.audio_in_queue = self.audio.audio_in_queue
            self.session._send_lock = asyncio.Lock()
            self._startup_lock = asyncio.Lock()
        self._resource_loop = loop

    async def _start_control(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._bind_loop_resources(self._loop)
        self._is_running = True

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
        return await self.vision.set_mode(normalized)


    async def start(self, *, start_hearing: bool = True) -> None:
        """Starts all Live subsystems within the current asyncio event loop."""
        await self._start_control()
        async with self._startup_lock:
            if not self.config.enabled:
                err = "Live speech is disabled by KRATOS_LIVE_ENABLED."
                self.status_hub.report_error("live_speech", err)
                return
            if not self._speech_started:
                if self.config.is_gemini_backend:
                    await self.audio.start_output_only()
                    self._session_task = asyncio.create_task(self.session.run_connection_loop(), name="kratos-live-session-loop")
                else:
                    self.status_hub.update(gemini_connected=False, live_health="native", current_state=LiveState.IDLE)
                self._speech_started = True
            if start_hearing and not self._hearing_started:
                try:
                    from .native_listener import get_native_hearing

                    def _on_heard(text: str) -> None:
                        if self.on_user_transcript:
                            try:
                                self.on_user_transcript(text)
                            except Exception:
                                logger.exception("[LiveRuntime] Kratos voice-input handler failed")

                    with self._lifecycle_lock:
                        self.native_hearing = get_native_hearing(on_transcription=_on_heard)
                        self.native_hearing.start()
                        self._hearing_started = True
                        self.status_hub.clear_error("speech_recognition")
                        self.status_hub.update(microphone_active=True, microphone_health="online")
                except Exception as exc:
                    self.status_hub.report_error("speech_recognition", str(exc) or type(exc).__name__)

    async def stop(self) -> None:
        """Stops all Live subsystems cleanly."""
        if not self._is_running:
            return
        self._is_running = False
        self._speech_started = False
        self._hearing_started = False

        logger.info("[LiveRuntime] Stopping Live subsystems...")
        if hasattr(self, "native_hearing") and self.native_hearing:
            try:
                self.native_hearing.stop()
            except Exception:
                pass
        self.status_hub.update(microphone_active=False, microphone_health="offline")

        if self._session_task and not self._session_task.done():
            self._session_task.cancel()
        await self.session.stop()
        if self._session_task:
            await asyncio.gather(self._session_task, return_exceptions=True)
            self._session_task = None
        await self.vision.stop()
        await self.audio.stop()

        logger.info("[LiveRuntime] Live subsystems stopped.")

    def start_in_background(self, *, start_hearing: bool = True, control_only: bool = False) -> None:
        """Launches the LiveRuntime in a dedicated background daemon thread."""
        def _worker() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            try:
                loop.run_until_complete(self._start_control())
                if self._requested_speech:
                    loop.run_until_complete(self.start(start_hearing=self._requested_hearing))
                if not self._is_running:
                    return
                loop.call_soon(self._ready.set)
                loop.run_forever()
            except Exception as e:
                self._start_error = str(e) or type(e).__name__
                self._ready.set()
                logger.warning(f"[LiveRuntime] Background thread error: {e}")
            finally:
                try:
                    loop.run_until_complete(self.stop())
                except Exception as exc:
                    logger.debug("Operation error suppressed: %s", exc)
                loop.close()
                self._ready.set()

        with self._lifecycle_lock:
            if self._thread and self._thread.is_alive():
                if not control_only:
                    self._requested_speech = True
                    self._requested_hearing = self._requested_hearing or start_hearing
                    if self._loop and not self._loop.is_closed():
                        asyncio.run_coroutine_threadsafe(self.start(start_hearing=start_hearing), self._loop)
                return
            self._ready.clear()
            self._start_error = None
            self._requested_speech = not control_only
            self._requested_hearing = start_hearing and not control_only
            self._thread = threading.Thread(target=_worker, daemon=True, name="kratos-live-runtime")
            self._thread.start()

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
