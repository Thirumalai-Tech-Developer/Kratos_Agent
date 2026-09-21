import unittest
import asyncio
from unittest.mock import MagicMock
from kratos_agent.core.dispute import is_dispute, handle_dispute, DISPUTE_TRIGGERS
from kratos_agent.core.evidence import Evidence, OutcomeAssertion

class TestDispute(unittest.TestCase):
    def test_trilingual_trigger_coverage(self):
        # English
        self.assertTrue(is_dispute("no it didn't open"))
        self.assertTrue(is_dispute("it's not playing"))
        self.assertTrue(is_dispute("you're lying"))
        self.assertTrue(is_dispute("check again please"))
        self.assertTrue(is_dispute("really?"))
        self.assertTrue(is_dispute("nothing happened"))

        # Tamil
        self.assertTrue(is_dispute("இல்லை ஆகவில்லை"))
        self.assertTrue(is_dispute("பாரு தப்பு"))
        self.assertTrue(is_dispute("திறக்கல"))

        # Tanglish (the observed user phrases)
        self.assertTrue(is_dispute("Ilaye, Chrome browser open pannala"))
        self.assertTrue(is_dispute("illa da"))
        self.assertTrue(is_dispute("open aagala"))
        self.assertTrue(is_dispute("Screen open aayiruchu paar athu paathu open pannu"))
        self.assertTrue(is_dispute("play aagala"))
        self.assertTrue(is_dispute("wrong ah irukku"))

        # Non-dispute phrases
        self.assertFalse(is_dispute("thank you jarvis"))
        self.assertFalse(is_dispute("what is the weather today?"))

    def test_dispute_forces_live_perception(self):
        # Mock runtime and ccs
        runtime = MagicMock()
        ccs = MagicMock()
        runtime.ccs = ccs
        runtime.verification = MagicMock()

        # Previous task claimed met=True
        task = MagicMock()
        task.goal = "Open Chrome and play video"
        task.claim = "video is playing"
        task.evidence = Evidence(claim="video is playing", method="cdp_js", met=True, observed={}, detail="claimed success")
        runtime.tasks = {"task_1": task}
        runtime.last_terminal_task.return_value = task

        # Live perception returns met=False (video was NOT actually playing)
        fresh_evidence = Evidence(
            claim="video is playing",
            method="cdp_js",
            met=False,
            observed={"paused": True, "currentTime": 0},
            detail="video element present but paused at 0:00"
        )
        runtime.verification.verify_observable_outcome.return_value = fresh_evidence

        # Run dispute handler
        res = asyncio.run(handle_dispute(runtime, task_id="task_1", observation="illa, open aagala"))

        # 1. Verify that LIVE perception was called (never skipped or answered from memory)
        self.assertTrue(runtime.verification.verify_observable_outcome.called)
        self.assertTrue(runtime.verification.verify_observable_outcome.call_args[1].get("require_fresh"))

        # 2. Verify retraction and status
        self.assertTrue(res.reverified)
        self.assertTrue(res.wrong)
        self.assertIsNotNone(res.retraction)
        self.assertIn("mistake", res.retraction.lower())

        # 3. Verify audit record
        self.assertTrue(runtime.audit.record.called)
        self.assertEqual(runtime.audit.record.call_args[1]["kind"], "FALSE_COMPLETION_CONFIRMED")

    def test_dispute_when_claim_was_actually_right(self):
        runtime = MagicMock()
        ccs = MagicMock()
        runtime.ccs = ccs
        runtime.verification = MagicMock()

        task = MagicMock()
        task.goal = "Open Chrome and play video"
        task.claim = "video is playing"
        task.primary_window = "Chrome"
        task.evidence = Evidence(claim="video is playing", method="cdp_js", met=True, observed={}, detail="claimed success")
        runtime.tasks = {"task_1": task}

        # Live perception confirms it IS playing
        fresh_evidence = Evidence(
            claim="video is playing",
            method="cdp_js",
            met=True,
            observed={"paused": False, "currentTime": 2.5},
            detail="advancing 2.5s"
        )
        runtime.verification.verify_observable_outcome.return_value = fresh_evidence

        res = asyncio.run(handle_dispute(runtime, task_id="task_1", observation="check again"))

        self.assertTrue(res.reverified)
        self.assertFalse(res.wrong)
        self.assertEqual(res.action, "explain")
        self.assertIn("IS", res.explanation)
        # Window brought forward
        ccs.window_action.assert_called_with("Chrome", "restore")
        ccs.focus_window.assert_called_with("Chrome")

if __name__ == "__main__":
    unittest.main()
