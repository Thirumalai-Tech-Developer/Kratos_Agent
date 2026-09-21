"""Speaker audio playback for Kratos Multimodal Live."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class SpeakerPlayer:
    """Plays 24kHz 16-bit PCM audio received from Gemini Live."""

    def __init__(
        self,
        audio_in_queue: asyncio.Queue[bytes],
        sample_rate: int = 24000,
        channels: int = 1,
    ) -> None:
        self.audio_in_queue = audio_in_queue
        self.sample_rate = sample_rate
        self.channels = channels
        self.is_running = False
        self.is_muted = False
        self.device_name: str = "Unknown"
        self._stream: Any = None

    def mute(self) -> None:
        self.is_muted = True
        self.clear()

    def unmute(self) -> None:
        self.is_muted = False

    def clear(self) -> None:
        """Clear all queued audio chunks immediately (used on interruption)."""
        while not self.audio_in_queue.empty():
            try:
                self.audio_in_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def run(self) -> None:
        """Runs the speaker playback loop."""
        self.is_running = True

        use_sounddevice = False
        try:
            import sounddevice as sd
            use_sounddevice = True
        except ImportError:
            pass

        if use_sounddevice:
            await self._run_sounddevice()
        else:
            await self._run_pyaudio()

    async def _run_sounddevice(self) -> None:
        import sounddevice as sd

        try:
            default_out = sd.default.device[1]
            device_info = sd.query_devices(default_out, 'output')
            self.device_name = device_info.get('name', 'Default Speaker')
            logger.info(f"[Speaker] Using output device: {self.device_name}")
        except Exception as e:
            logger.warning(f"[Speaker] Could not query default output device: {e}")
            self.device_name = "Default Speaker"

        try:
            self._stream = sd.RawOutputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype='int16',
            )
            self._stream.start()
        except Exception as e:
            logger.warning(f"[Speaker] Failed to open speaker stream: {e}")
            self.is_running = False
            return

        try:
            while self.is_running:
                audio_data = await self.audio_in_queue.get()
                if not audio_data or self.is_muted:
                    continue

                await asyncio.to_thread(
                    self._stream.write, audio_data
                )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"[Speaker] Playback error: {e}")
        finally:
            self.is_running = False
            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None

    async def _run_pyaudio(self) -> None:
        try:
            import pyaudio
        except ImportError:
            logger.warning("[Speaker] Neither sounddevice nor pyaudio is installed. Speaker offline.")
            self.is_running = False
            return

        pya = None
        try:
            pya = pyaudio.PyAudio()
            self._stream = await asyncio.to_thread(
                pya.open,
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                output=True,
            )
        except Exception as e:
            logger.warning(f"[Speaker] Failed to open PyAudio speaker: {e}")
            self.is_running = False
            if pya:
                try:
                    pya.terminate()
                except Exception:
                    pass
            return

        try:
            while self.is_running:
                audio_data = await self.audio_in_queue.get()
                if not audio_data or self.is_muted:
                    continue

                await asyncio.to_thread(
                    self._stream.write, audio_data
                )
        except asyncio.CancelledError:
            pass
        finally:
            self.is_running = False
            if self._stream:
                try:
                    self._stream.stop_stream()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            if pya:
                try:
                    pya.terminate()
                except Exception:
                    pass

    def stop(self) -> None:
        self.is_running = False
        self.clear()
        if self._stream:
            try:
                if hasattr(self._stream, "stop"):
                    self._stream.stop()
                elif hasattr(self._stream, "stop_stream"):
                    self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
