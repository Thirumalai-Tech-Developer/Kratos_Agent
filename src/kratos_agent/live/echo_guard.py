"""Voice echo guard preventing TTS output from being captured as user input (§27, §28, §29)."""
from __future__ import annotations

import time
from enum import Enum


class VoiceSource(str, Enum):
    USER_MIC = "user_mic"
    TTS_OUTPUT = "tts_output"
    SYSTEM = "system"
    TERMINAL = "terminal"


class VoiceEchoGuard:
    """Guards the audio input pipeline while Kratos or Gemini Live is speaking."""

    def __init__(self, ignore_window_ms: int = 500) -> None:
        self.is_speaking: bool = False
        self.last_speech_time: float = 0.0
        self.ignore_window_ms: int = ignore_window_ms

    def start_speaking(self) -> None:
        """Mark that TTS or speech output has started."""
        self.is_speaking = True

    def stop_speaking(self) -> None:
        """Mark that TTS or speech output has completed."""
        self.is_speaking = False
        self.last_speech_time = time.time()

    def should_suppress_mic(self) -> bool:
        """Returns True if microphone input should be suppressed due to active speech or echo tail (§29)."""
        if self.is_speaking:
            return True
        elapsed_ms = (time.time() - self.last_speech_time) * 1000.0
        return elapsed_ms < self.ignore_window_ms

    def can_create_task(self, source: VoiceSource) -> bool:
        """Enforces that only USER_MIC source can create user tasks (§28)."""
        return source == VoiceSource.USER_MIC


_echo_guard: VoiceEchoGuard | None = None


def get_echo_guard() -> VoiceEchoGuard:
    global _echo_guard
    if _echo_guard is None:
        _echo_guard = VoiceEchoGuard()
    return _echo_guard
