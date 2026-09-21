"""Audio subsystem manager for Kratos Multimodal Live."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

from .events import LiveState, LiveStatusHub
from .microphone import MicrophoneListener, get_input_devices
from .speaker import SpeakerPlayer

logger = logging.getLogger(__name__)


class AudioManager:
    """Coordinates microphone input, speaker playback, queues, and interruptions."""

    def __init__(
        self,
        out_queue: asyncio.Queue[Dict[str, Any]],
        status_hub: Optional[LiveStatusHub] = None,
        send_sample_rate: int = 16000,
        receive_sample_rate: int = 24000,
        chunk_size: int = 1024,
        device: Optional[int | str] = None,
        vad_threshold: int = 80,
        vad_silence_seconds: float = 1.2,
    ) -> None:
        self.out_queue = out_queue
        self.audio_in_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.status_hub = status_hub

        self.mic = MicrophoneListener(
            out_queue=self.out_queue,
            sample_rate=send_sample_rate,
            chunk_size=chunk_size,
            device=device,
            vad_threshold=vad_threshold,
            vad_silence_seconds=vad_silence_seconds,
            on_speech_started=self._on_speech_started,
            on_speech_stopped=self._on_speech_stopped,
            on_interruption=self._on_interruption,
            status_hub=self.status_hub,
        )
        self.speaker = SpeakerPlayer(
            audio_in_queue=self.audio_in_queue,
            sample_rate=receive_sample_rate,
        )
        self._tasks: list[asyncio.Task[Any]] = []

    def _on_speech_started(self) -> None:
        """Invoked immediately when local VAD detects user has started speaking."""
        if self.status_hub:
            self.status_hub.update(current_state=LiveState.LISTENING)

        # Immediate local interruption if assistant is currently speaking or has queued audio
        is_speaking = (
            self.status_hub is not None and self.status_hub.status.current_state == LiveState.SPEAKING
        )
        has_pending_audio = not self.audio_in_queue.empty()
        if self.speaker.is_running and (is_speaking or has_pending_audio):
            logger.info("[AudioManager] User started speaking while assistant active. Immediate interruption triggered.")
            self.handle_interruption()

    def _on_speech_stopped(self) -> None:
        """Invoked when user speech ceases and silence threshold is reached."""
        if self.status_hub and self.status_hub.status.current_state == LiveState.LISTENING:
            if not self.status_hub.status.active_task_id:
                self.status_hub.update(current_state=LiveState.THINKING)

    def _on_interruption(self) -> None:
        """Invoked when speech starts to verify interruption."""
        if self.status_hub and self.status_hub.status.current_state == LiveState.SPEAKING:
            self.handle_interruption()

    @property
    def is_muted(self) -> bool:
        return self.mic.is_muted

    def mute(self) -> None:
        self.mic.mute()
        self.speaker.mute()
        if self.status_hub:
            self.status_hub.update(muted=True)

    def unmute(self) -> None:
        self.mic.unmute()
        self.speaker.unmute()
        if self.status_hub:
            self.status_hub.update(muted=False)

    def handle_interruption(self) -> None:
        """Called when Gemini Live or local VAD detects that user has interrupted."""
        self.speaker.clear()
        if self.status_hub and self.status_hub.status.current_state == LiveState.SPEAKING:
            self.status_hub.update(current_state=LiveState.LISTENING)

    def get_input_devices(self) -> List[Dict[str, Any]]:
        """Returns list of available microphone input devices."""
        return get_input_devices()

    def get_active_microphone_name(self) -> str:
        """Returns the name of the currently active microphone."""
        return self.mic.device_name

    async def set_device(self, device: Optional[int | str]) -> str:
        """Dynamically switches active microphone device at runtime."""
        self.mic.stop()
        self.mic.device = device
        self.mic.device_index, self.mic.device_name = self.mic._resolve_device()

        # Stop existing mic task if running
        for t in list(self._tasks):
            if t.get_name() == "kratos-live-mic":
                t.cancel()
                self._tasks.remove(t)

        async def _run_mic():
            await self.mic.run()
            if self.status_hub:
                self.status_hub.update(microphone_active=self.mic.is_running)

        t_mic = asyncio.create_task(_run_mic(), name="kratos-live-mic")
        self._tasks.append(t_mic)
        await asyncio.sleep(0.05)
        logger.info(f"[AudioManager] Switched active microphone to: {self.mic.device_name}")
        return self.mic.device_name

    async def start(self) -> None:
        """Start both microphone and speaker background tasks."""
        async def _run_mic():
            await self.mic.run()
            if self.status_hub:
                self.status_hub.update(microphone_active=self.mic.is_running)

        async def _run_speaker():
            await self.speaker.run()
            if self.status_hub:
                self.status_hub.update(speaker_active=self.speaker.is_running)

        t_mic = asyncio.create_task(_run_mic(), name="kratos-live-mic")
        t_spk = asyncio.create_task(_run_speaker(), name="kratos-live-speaker")
        self._tasks = [t_mic, t_spk]

        # Short pause to let them initialize and report status
        await asyncio.sleep(0.05)
        if self.status_hub:
            self.status_hub.update(
                microphone_active=self.mic.is_running,
                speaker_active=self.speaker.is_running,
            )

    async def stop(self) -> None:
        """Stop microphone and speaker tasks and close streams."""
        self.mic.stop()
        self.speaker.stop()
        for t in self._tasks:
            if not t.done():
                t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        if self.status_hub:
            self.status_hub.update(microphone_active=False, speaker_active=False)
