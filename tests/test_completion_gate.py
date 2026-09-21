import unittest
from pathlib import Path
from kratos_agent.core.evidence import Evidence, OutcomeAssertion
from kratos_agent.core.verification_manager import VerificationManager, Verdict
from kratos_agent.core.task_manager import TaskItem, TaskState

class TestCompletionGate(unittest.TestCase):
    def setUp(self):
        self.vm = VerificationManager(Path.cwd())

    def test_informational_task_allowed_without_evidence(self):
        task = TaskItem(id="1", title="What is the weather?", requires_observable_evidence=False)
        verdict = self.vm.gate_completion(task, {"summary": "weather info"}, None)
        self.assertTrue(verdict.allow)
        self.assertEqual(verdict.reason, "informational_task")

    def test_no_evidence_returns_correction(self):
        task = TaskItem(
            id="2",
            title="Play God of War on YouTube",
            requires_observable_evidence=True,
            assertion=OutcomeAssertion(kind="media_playing", params={"min_advance_s": 0.5}),
        )
        verdict = self.vm.gate_completion(task, {"summary": "done"}, None)
        self.assertFalse(verdict.allow)
        self.assertEqual(verdict.code, "NO_EVIDENCE")
        self.assertIn("Dispatching an action is not completing it", verdict.correction)
        self.assertIn("media_playing", verdict.correction)

    def test_unverified_outcome_returns_correction(self):
        task = TaskItem(
            id="3",
            title="Play God of War on YouTube",
            requires_observable_evidence=True,
            assertion=OutcomeAssertion(kind="media_playing", params={"min_advance_s": 0.5}),
        )
        evidence = Evidence(
            claim="video is playing",
            method="cdp_js",
            met=False,
            observed={"paused": True, "currentTime": 0},
            detail="video element present but paused at 0:00",
        )
        verdict = self.vm.gate_completion(task, {"summary": "done"}, evidence)
        self.assertFalse(verdict.allow)
        self.assertEqual(verdict.code, "UNVERIFIED_OUTCOME")
        self.assertIn("video element present but paused at 0:00", verdict.correction)

    def test_trustworthy_evidence_allowed(self):
        task = TaskItem(
            id="4",
            title="Play God of War on YouTube",
            requires_observable_evidence=True,
            assertion=OutcomeAssertion(kind="media_playing", params={"min_advance_s": 0.5}),
        )
        evidence = Evidence(
            claim="video is playing",
            method="cdp_js",
            met=True,
            observed={"paused": False, "currentTime": 2.1},
            confidence=1.0,
            samples=2,
            detail="playing at 2.1 s, 1080p",
            stale_ms=50,
        )
        verdict = self.vm.gate_completion(task, {"summary": "playing video"}, evidence)
        self.assertTrue(verdict.allow)
        self.assertEqual(verdict.reason, "evidence_met")
        self.assertIsNotNone(verdict.evidence)
        self.assertTrue(verdict.evidence.met)

if __name__ == "__main__":
    unittest.main()
