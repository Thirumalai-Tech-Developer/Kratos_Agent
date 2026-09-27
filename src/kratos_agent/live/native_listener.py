"""Native speech recognition and hearing listener for Kratos Agent.

Provides local speech recognition using Windows Speech Recognition (System.Speech.Recognition / SAPI),
completely removing dependency on external Gemini Live audio streaming.
"""
from __future__ import annotations

import logging
import subprocess
import threading
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("kratos.hearing")


class NativeHearingListener:
    """Captures microphone audio and transcribes speech to text locally on Windows."""

    def __init__(
        self,
        on_transcription: Callable[[str], None] | None = None,
        device_name: str = "Default Microphone",
    ) -> None:
        self.on_transcription = on_transcription
        self.device_name = device_name
        self.is_running = False
        self.is_muted = False
        self._thread: threading.Thread | None = None
        self._process: subprocess.Popen[str] | None = None

    def start(self) -> None:
        """Starts the background speech listener."""
        if self.is_running:
            return
        self.is_running = True
        self._thread = threading.Thread(target=self._run_listener, daemon=True, name="kratos-native-hearing")
        self._thread.start()
        logger.info("[NativeHearing] Local speech listener started.")

    def stop(self) -> None:
        """Stops the speech listener."""
        self.is_running = False
        if self._process:
            try:
                self._process.terminate()
            except Exception:
                pass
            self._process = None

    def mute(self) -> None:
        self.is_muted = True

    def unmute(self) -> None:
        self.is_muted = False

    def _run_listener(self) -> None:
        """Runs Windows System.Speech.Recognition continuous recognition loop via PowerShell."""
        ps_script = """
Add-Type -AssemblyName System.Speech
$rec = New-Object System.Speech.Recognition.SpeechRecognitionEngine
$grammar = New-Object System.Speech.Recognition.DictationGrammar
$rec.LoadGrammar($grammar)
$rec.SetInputToDefaultAudioDevice()

Register-ObjectEvent -InputObject $rec -EventName "SpeechRecognized" -Action {
    $txt = $EventArgs.Result.Text
    if ($txt -and $txt.Trim().Length -gt 0) {
        [Console]::WriteLine("[HEARD]:" + $txt)
        [Console]::Out.Flush()
    }
} | Out-Null

$rec.RecognizeAsync([System.Speech.Recognition.RecognizeMode]::Multiple)

while ($true) {
    Start-Sleep -Milliseconds 250
}
"""
        try:
            self._process = subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            if self._process.stdout:
                for line in self._process.stdout:
                    if not self.is_running:
                        break
                    line_str = line.strip()
                    if line_str.startswith("[HEARD]:"):
                        text = line_str[8:].strip()
                        if text and not self.is_muted:
                            logger.info(f"[NativeHearing] Heard: {text}")
                            if self.on_transcription:
                                try:
                                    self.on_transcription(text)
                                except Exception as exc:
                                    logger.debug("Transcription callback error: %s", exc)
        except Exception as e:
            logger.debug(f"[NativeHearing] Listener process ended: {e}")
        finally:
            self.is_running = False


_hearing_listener: NativeHearingListener | None = None


def get_native_hearing(on_transcription: Callable[[str], None] | None = None) -> NativeHearingListener:
    global _hearing_listener
    if _hearing_listener is None:
        _hearing_listener = NativeHearingListener(on_transcription=on_transcription)
    elif on_transcription:
        _hearing_listener.on_transcription = on_transcription
    return _hearing_listener
