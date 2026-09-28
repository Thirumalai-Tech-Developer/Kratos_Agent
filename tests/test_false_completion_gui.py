import unittest
from unittest.mock import MagicMock
from kratos_agent.core.evidence import Evidence, OutcomeAssertion
from kratos_agent.core.verification_manager import VerificationManager, Verdict
from kratos_agent.core.runtime_contracts import TerminalLatch
from kratos_agent.ccs.perception.blockers import detect_blockers, clear_blocker, Blocker

class TestFalseCompletionGui(unittest.TestCase):
    def setUp(self):
        self.verif = VerificationManager(workspace=MagicMock())
        self.latch = TerminalLatch()

    def test_media_playing_unverified_refuses_completion(self):
        # Task requires observable evidence of media_playing
        task = MagicMock()
        task.task_id = "task_youtube_1"
        task.requires_observable_evidence = True
        task.assertion = OutcomeAssertion(kind="media_playing", params={"min_advance_s": 0.5}, require_samples=2)

        # 1. No evidence provided
        verdict = self.verif.gate_completion(task, declared_result={"status": "done"}, evidence=None)
        self.assertFalse(verdict.allow)
        self.assertEqual(verdict.code, "NO_EVIDENCE")
        self.assertIn("Dispatching an action is not completing it", verdict.correction)

        # 2. False evidence provided (video paused at 0:00)
        unmet_evidence = Evidence(
            claim="video is playing",
            method="cdp_js",
            met=False,
            observed={"paused": True, "currentTime": 0.0},
            detail="video element present but paused at 0:00",
        )
        verdict2 = self.verif.gate_completion(task, declared_result={"status": "done"}, evidence=unmet_evidence)
        self.assertFalse(verdict2.allow)
        self.assertEqual(verdict2.code, "UNVERIFIED_OUTCOME")
        self.assertIn("video element present but paused", verdict2.correction)

        # 3. Latch must NOT be set to COMPLETED
        self.assertNotIn("task_youtube_1", self.latch._set)

    def test_youtube_bot_wall_honest_failure(self):
        # When bot wall is present, clear_blocker reports honest failure
        ccs = MagicMock()
        ev = clear_blocker(ccs, "youtube_bot_wall")
        self.assertFalse(ev.met)
        self.assertIn("sign-in", ev.detail.lower())

    def test_exactly_one_terminal_status_guaranteed(self):
        task_id = "task_yt_play"
        # First terminal status: FAILED
        first_ok = self.latch.try_set(task_id, "FAILED")
        self.assertTrue(first_ok)

        # Second terminal status attempt: COMPLETED (the observed contradictory defect)
        second_ok = self.latch.try_set(task_id, "COMPLETED")
        self.assertFalse(second_ok, "TerminalLatch MUST refuse contradictory terminal status")

if __name__ == "__main__":
    unittest.main()
