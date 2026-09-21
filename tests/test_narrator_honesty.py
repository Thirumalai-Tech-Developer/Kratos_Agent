import unittest
from unittest.mock import MagicMock
from kratos_agent.live.narration import NarrationManager
from kratos_agent.core.runtime_contracts import RuntimeEvent, EventKind

class TestNarratorHonesty(unittest.TestCase):
    def setUp(self):
        self.spoken = []
        self.narrator = NarrationManager(
            send_speech_fn=lambda text: self.spoken.append(text),
            min_interval_seconds=0.0,
        )
        self.narrator.is_active = True

    def test_unverified_success_claim_is_suppressed(self):
        # Event declares turn completed without evidence.met
        event = RuntimeEvent(
            kind=EventKind.TURN_COMPLETED,
            payload={
                "status": "completed",
                "requires_observable_evidence": True,
                "evidence": {"met": False, "detail": "not playing"},
            },
        )
        self.narrator.on_event(event)

        # Ensure no success words were spoken
        for msg in self.spoken:
            self.assertNotIn("completed successfully", msg.lower())
            self.assertNotIn("verified", msg.lower())
            self.assertNotIn("வெற்றி", msg)
            self.assertNotIn("முடிவடை", msg)

    def test_verified_success_speaks_evidence(self):
        event = RuntimeEvent(
            kind=EventKind.TURN_COMPLETED,
            payload={
                "status": "completed",
                "evidence": {"met": True, "detail": "video playing at 1.9s, 1080p"},
            },
        )
        self.narrator.on_event(event)

        self.assertEqual(len(self.spoken), 1)
        self.assertIn("video playing at 1.9s", self.spoken[0])

    def test_false_completion_speaks_correction_promptly(self):
        event = RuntimeEvent(
            kind=EventKind.FALSE_COMPLETION,
            payload={
                "task_id": "t1",
                "correction": "The video was checked and is paused at 0:00.",
            },
        )
        self.narrator.on_event(event)

        self.assertEqual(len(self.spoken), 1)
        self.assertIn("didn't actually work", self.spoken[0].lower())
        self.assertIn("paused at 0:00", self.spoken[0])

    def test_retraction_is_spoken_first(self):
        event = RuntimeEvent(
            kind=EventKind.RETRACTION,
            payload={
                "task_id": "t1",
                "correction": "You're right — it's not playing. YouTube is on the home page.",
            },
        )
        self.narrator.on_event(event)

        self.assertEqual(len(self.spoken), 1)
        self.assertIn("You're right", self.spoken[0])

if __name__ == "__main__":
    unittest.main()
