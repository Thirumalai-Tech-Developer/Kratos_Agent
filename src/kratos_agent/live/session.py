"""Gemini Live audio output session for Kratos Agent.

Kratos owns all reasoning, tool selection, and execution. This session accepts
only explicitly marked speech text and returns generated audio.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from google import genai
from google.genai import types

from .audio import AudioManager
from .config import LiveConfig
from .events import LiveState, LiveStatusHub

logger = logging.getLogger(__name__)

SPEECH_SYSTEM_PROMPT = """You are a speech renderer for Kratos Agent.
Your only job is to speak the supplied text as audio. Do not answer questions,
solve tasks, infer intent, summarize, add commentary, or use tools. Speak only
the supplied text, preserving its language and meaning. If no speech text is
provided, produce no response. Never request or process microphone, camera, or
screen input."""


class LiveSession:
    """Maintains a Gemini Live connection used only for marked speech output."""

    def __init__(
        self,
        config: LiveConfig,
        out_queue: asyncio.Queue[dict[str, Any]],
        audio_manager: AudioManager,
        status_hub: LiveStatusHub | None = None,
        on_model_transcript: Any | None = None,
    ) -> None:
        self.config = config
        self.out_queue = out_queue
        self.audio_manager = audio_manager
        self.status_hub = status_hub
        self.on_model_transcript = on_model_transcript
        self.session: Any = None
        self.is_running = False
        self._tasks: list[asyncio.Task[Any]] = []
        self._send_lock = asyncio.Lock()
        self._last_heartbeat = 0.0
        self._last_logged_error = ""
        self._last_logged_error_time = 0.0

    def get_diagnostics(self) -> dict[str, Any]:
        heartbeat_age = (
            None if self._last_heartbeat <= 0
            else round(max(0.0, time.time() - self._last_heartbeat), 3)
        )
        return {
            "model": self.config.model,
            "purpose": "speech_output_only",
            "connected": self.session is not None,
            "running": self.is_running,
            "healthy": self.is_healthy(),
            "heartbeat_age_s": heartbeat_age,
            "last_error": self.status_hub.status.last_error if self.status_hub else None,
            "last_error_component": self.status_hub.status.last_error_component if self.status_hub else None,
        }

    def _build_connect_config(self) -> types.LiveConnectConfig:
        """Build a speech-only session with no tools or incoming media modes."""
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self.config.voice_name,
                    )
                )
            ),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            system_instruction=types.Content(
                parts=[types.Part.from_text(text=SPEECH_SYSTEM_PROMPT)]
            ),
        )

    async def receive_loop(self) -> None:
        """Play generated audio and surface its transcript; ignore all tool/input events."""
        try:
            while self.is_running and self.session is not None:
                async for response in self.session.receive():
                    if not self.is_running:
                        break
                    self._last_heartbeat = time.time()
                    if self.status_hub:
                        self.status_hub.update(last_heartbeat=self._last_heartbeat)

                    if getattr(response, "tool_call", None):
                        logger.warning("[LiveSession] Ignoring an unexpected tool call in speech-only mode.")

                    server_content = getattr(response, "server_content", None)
                    if server_content is None:
                        continue

                    if getattr(server_content, "interrupted", False):
                        from .echo_guard import get_echo_guard
                        get_echo_guard().stop_speaking()
                        if self.status_hub:
                            self.status_hub.update(current_state=LiveState.IDLE)
                        continue

                    model_turn = getattr(server_content, "model_turn", None)
                    if model_turn and hasattr(model_turn, "parts"):
                        for part in model_turn.parts:
                            inline = getattr(part, "inline_data", None)
                            if inline and inline.data:
                                from .echo_guard import get_echo_guard
                                get_echo_guard().start_speaking()
                                try:
                                    self.audio_manager.audio_in_queue.put_nowait(inline.data)
                                except asyncio.QueueFull:
                                    try:
                                        self.audio_manager.audio_in_queue.get_nowait()
                                    except asyncio.QueueEmpty:
                                        pass
                                    self.audio_manager.audio_in_queue.put_nowait(inline.data)

                    out_tx = getattr(server_content, "output_transcription", None)
                    text = str(getattr(out_tx, "text", "") or "").strip()
                    if text and self.on_model_transcript:
                        try:
                            self.on_model_transcript(text)
                        except Exception as exc:
                            logger.debug("Speech transcript callback failed: %s", exc)

                    if getattr(server_content, "turn_complete", False) and self.status_hub:
                        self.status_hub.update(current_state=LiveState.IDLE)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            message = str(exc).strip() or type(exc).__name__
            logger.warning("[LiveSession] Speech receive loop failed: %s", message)
            if self.status_hub:
                self.status_hub.report_error("gemini_speech", message)

    async def speak_text(self, text: str) -> None:
        """Ask Gemini to render a pre-authorized phrase as audio, without extending it."""
        clean = self._sanitize_speech(text)
        if not clean or self.session is None or not self.is_running:
            return
        prompt = (
            "Render only the following approved phrase as spoken audio. "
            "Do not add words or respond to its meaning:\n" + clean
        )
        try:
            if self.status_hub:
                self.status_hub.update(current_state=LiveState.SPEAKING)
            async with self._send_lock:
                if self.session is not None and self.is_running:
                    await self.session.send(input=prompt, end_of_turn=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("[LiveSession] Could not send marked speech to Gemini: %s", exc)
            if self.status_hub:
                self.status_hub.report_error("gemini_speech", str(exc) or type(exc).__name__)

    @staticmethod
    def _sanitize_speech(text: str) -> str:
        text = re.sub(r"```[\s\S]*?```", "", str(text or ""))
        text = re.sub(r"\x1b\[[0-9;]*[mK]", "", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
        text = re.sub(r"[*_#`]", "", text)
        text = re.sub(r"https?://\S+|www\.\S+", "", text)
        text = re.sub(r"\b(?:api[_-]?key|token|secret|password)\s*[:=]\s*\S+", "[redacted]", text, flags=re.I)
        return " ".join(text.split())[:240].strip()

    def is_healthy(self) -> bool:
        if not self.is_running or self.session is None:
            return False
        recv_task = next((task for task in self._tasks if task.get_name() == "kratos-live-speech-recv"), None)
        if recv_task is None or recv_task.done():
            return False
        return not self._last_heartbeat or (time.time() - self._last_heartbeat) <= 90.0

    async def run_connection_loop(self) -> None:
        """Connect and retry with bounded backoff; failures affect speech only."""
        self.is_running = True
        client = genai.Client(api_key=self.config.api_key)
        connect_config = self._build_connect_config()
        backoff_delays = (1.0, 2.0, 4.0, 8.0, 15.0)
        backoff_index = 0

        while self.is_running:
            try:
                if self.status_hub:
                    self.status_hub.update(current_state=LiveState.CONNECTING, live_health="connecting")
                async with client.aio.live.connect(model=self.config.model, config=connect_config) as session:
                    self.session = session
                    backoff_index = 0
                    self._last_heartbeat = time.time()
                    if self.status_hub:
                        self.status_hub.clear_error("gemini_speech")
                        self.status_hub.update(
                            gemini_connected=True,
                            live_health="online",
                            last_heartbeat=self._last_heartbeat,
                            current_state=LiveState.CONNECTED,
                        )
                    receive_task = asyncio.create_task(
                        self.receive_loop(), name="kratos-live-speech-recv"
                    )
                    self._tasks = [receive_task]
                    await receive_task
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.session = None
                message = re.sub(r"(AIza[0-9A-Za-z_-]{20,}|sk-[A-Za-z0-9]{20,})", "[REDACTED]", str(exc))
                now = time.time()
                if message != self._last_logged_error or now - self._last_logged_error_time > 60:
                    logger.warning("[LiveSession] Speech connection failed: %s", message)
                    self._last_logged_error = message
                    self._last_logged_error_time = now
                if self.status_hub:
                    self.status_hub.report_error("gemini_speech", message)
                    self.status_hub.update(
                        gemini_connected=False,
                        current_state=LiveState.RECONNECTING,
                        live_health="reconnecting",
                    )
                if not self.is_running:
                    break
                await asyncio.sleep(backoff_delays[min(backoff_index, len(backoff_delays) - 1)])
                backoff_index = min(backoff_index + 1, len(backoff_delays) - 1)
            finally:
                self.session = None
                if self.status_hub and not self.is_running:
                    self.status_hub.update(
                        gemini_connected=False,
                        current_state=LiveState.DISCONNECTED,
                        live_health="offline",
                    )

    async def stop(self) -> None:
        self.is_running = False
        if self.status_hub:
            self.status_hub.update(current_state=LiveState.STOPPING)
        for task in self._tasks:
            if not task.done():
                task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        self.session = None
        if self.status_hub:
            self.status_hub.update(
                gemini_connected=False,
                current_state=LiveState.DISCONNECTED,
                live_health="offline",
            )
