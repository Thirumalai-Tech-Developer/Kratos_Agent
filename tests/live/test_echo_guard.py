"""Unit tests for VoiceEchoGuard and VoiceSource (§27, §28, §29)."""
from __future__ import annotations

import time
import unittest

from kratos_agent.live.echo_guard import VoiceEchoGuard, VoiceSource


class TestEchoGuard(unittest.TestCase):
    def setUp(self) -> None:
        self.guard = VoiceEchoGuard(ignore_window_ms=200)

    def test_voice_source_filtering(self) -> None:
        self.assertTrue(self.guard.can_create_task(VoiceSource.USER_MIC))
        self.assertFalse(self.guard.can_create_task(VoiceSource.TTS_OUTPUT))
        self.assertFalse(self.guard.can_create_task(VoiceSource.SYSTEM))
        self.assertFalse(self.guard.can_create_task(VoiceSource.TERMINAL))

    def test_echo_suppression_during_and_after_speech(self) -> None:
        # Initially not speaking
        self.assertFalse(self.guard.should_suppress_mic())

        # Start speaking -> microphone must be suppressed
        self.guard.start_speaking()
        self.assertTrue(self.guard.should_suppress_mic())

        # Stop speaking -> still suppressed during ignore window
        self.guard.stop_speaking()
        self.assertTrue(self.guard.should_suppress_mic())

        # After ignore window expires -> microphone is active again
        time.sleep(0.25)
        self.assertFalse(self.guard.should_suppress_mic())


if __name__ == "__main__":
    unittest.main()
