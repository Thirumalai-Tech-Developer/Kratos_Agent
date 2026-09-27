"""Native Sovereign Voice (TTS) engine for Kratos Agent.

Provides local speech synthesis via Windows SAPI (comtypes) and PowerShell fallback,
completely removing dependency on external Gemini Live voice streaming.
"""
from __future__ import annotations

import logging
import re
import subprocess
import threading
from typing import Any

logger = logging.getLogger("kratos.voice")

# Filter out markdown formatting, URLs, code blocks, and internal reasoning from spoken text
CODE_BLOCK_PATTERN = re.compile(r"```[\s\S]*?```")
INLINE_CODE_PATTERN = re.compile(r"`([^`]+)`")
URL_PATTERN = re.compile(r"https?://\S+")
MARKDOWN_CHARS_PATTERN = re.compile(r"[*_#~|\[\]<>]")


def clean_text_for_speech(text: str) -> str:
    """Cleans code blocks, URLs, and markdown tokens from text so it sounds natural."""
    if not text:
        return ""
    # Strip full code blocks
    cleaned = CODE_BLOCK_PATTERN.sub(" [code block] ", text)
    # Strip URLs
    cleaned = URL_PATTERN.sub(" [link] ", cleaned)
    # Clean inline backticks
    cleaned = INLINE_CODE_PATTERN.sub(r"\1", cleaned)
    # Strip markdown symbols
    cleaned = MARKDOWN_CHARS_PATTERN.sub("", cleaned)
    # Collapse excess whitespace
    cleaned = " ".join(cleaned.split()).strip()
    return cleaned


class NativeVoiceEngine:
    """Local text-to-speech engine using Windows SAPI and PowerShell fallback."""

    def __init__(
        self,
        rate: int = 1,
        volume: int = 90,
        enabled: bool = True,
    ) -> None:
        self.rate = rate
        self.volume = volume
        self.is_muted = not enabled
        self._lock = threading.Lock()
        self._sapi_voice: Any = None
        self._initialized = False

    def _init_sapi(self) -> bool:
        if self._initialized:
            return self._sapi_voice is not None
        self._initialized = True
        try:
            import comtypes.client
            self._sapi_voice = comtypes.client.CreateObject("SAPI.SpVoice")
            self._sapi_voice.Rate = self.rate
            self._sapi_voice.Volume = self.volume
            logger.info("[NativeVoice] SAPI.SpVoice initialized successfully.")
            return True
        except Exception as exc:
            logger.debug("[NativeVoice] comtypes SAPI init failed: %s; using PowerShell fallback.", exc)
            self._sapi_voice = None
            return False

    def speak(self, text: str, interrupt: bool = False) -> None:
        """Speaks the text asynchronously without blocking the caller."""
        if self.is_muted or not text:
            return

        clean = clean_text_for_speech(text)
        if not clean:
            return

        with self._lock:
            # 1. Try Windows SAPI directly
            if self._init_sapi() and self._sapi_voice:
                try:
                    # SVSFlagsAsync = 1, SVSFPurgeBeforeSpeak = 2
                    flags = 1
                    if interrupt:
                        flags |= 2
                    self._sapi_voice.Speak(clean, flags)
                    return
                except Exception as exc:
                    logger.debug("[NativeVoice] SAPI speak error: %s", exc)

            # 2. PowerShell speech fallback in background thread
            def _ps_speak():
                try:
                    escaped = clean.replace('"', '""').replace("'", "''")
                    ps_cmd = (
                        f"Add-Type -AssemblyName System.Speech; "
                        f"$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                        f"$synth.Rate = {self.rate}; "
                        f"$synth.Volume = {self.volume}; "
                        f"$synth.Speak(\"{escaped}\")"
                    )
                    subprocess.run(
                        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                        capture_output=True,
                        timeout=15,
                    )
                except Exception as e:
                    logger.debug("[NativeVoice] PowerShell TTS fallback error: %s", e)

            threading.Thread(target=_ps_speak, daemon=True).start()

    def stop(self) -> None:
        """Interrupts and silences current speech."""
        with self._lock:
            if self._sapi_voice:
                try:
                    # SVSFPurgeBeforeSpeak = 2, SVSFlagsAsync = 1
                    self._sapi_voice.Speak("", 3)
                except Exception:
                    pass

    def mute(self) -> None:
        """Mutes voice output."""
        self.is_muted = True
        self.stop()

    def unmute(self) -> None:
        """Unmutes voice output."""
        self.is_muted = False

    def set_rate(self, rate: int) -> None:
        """Adjusts speech rate (-10 to 10)."""
        self.rate = max(-10, min(10, rate))
        if self._sapi_voice:
            try:
                self._sapi_voice.Rate = self.rate
            except Exception:
                pass

    def set_volume(self, volume: int) -> None:
        """Adjusts speech volume (0 to 100)."""
        self.volume = max(0, min(100, volume))
        if self._sapi_voice:
            try:
                self._sapi_voice.Volume = self.volume
            except Exception:
                pass


_voice_engine: NativeVoiceEngine | None = None


def get_native_voice() -> NativeVoiceEngine:
    global _voice_engine
    if _voice_engine is None:
        _voice_engine = NativeVoiceEngine()
    return _voice_engine
