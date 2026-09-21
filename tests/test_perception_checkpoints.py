import unittest
from unittest.mock import patch, MagicMock
from kratos_agent.ccs.tasks import computer_task
from kratos_agent.core.evidence import Evidence, OutcomeAssertion

class MockCCS:
    def __init__(self, is_playing=True):
        self.is_playing = is_playing

    def cdp_eval(self, script):
        return {"value": self.is_playing}

    def browser_js(self, script):
        return {"value": self.is_playing}

class TestPerceptionCheckpoints(unittest.TestCase):
    @patch("kratos_agent.ccs.tasks.take_screenshot", return_value=(b"fake_png", "frame_123"))
    @patch("kratos_agent.ccs.tasks.compute_screen_diff", return_value=(True, 1500))
    @patch("kratos_agent.ccs.tasks.detect_blockers", return_value=[])
    def test_computer_task_checkpoints_on_success(self, mock_blockers, mock_diff, mock_screen):
        ccs = MockCCS(is_playing=True)
        assertion = OutcomeAssertion(kind="media_playing", params={"min_advance_s": 0.5})

        with patch("kratos_agent.ccs.assertions.assertion_runner.run") as mock_assert_run:
            mock_assert_run.return_value = Evidence(
                claim="video is playing",
                method="cdp_js",
                met=True,
                observed={"paused": False, "currentTime": 2.5},
                confidence=1.0,
                samples=2,
                detail="playing at 2.5s",
                stale_ms=10,
            )
            res = computer_task("Play God of War", ccs, assertion=assertion)
            self.assertTrue(res.ok)
            checkpoints = res.data["checkpoints"]
            self.assertIn("PRE", checkpoints)
            self.assertIn("PRE_CLAIM", checkpoints)
            self.assertIn("timing", res.data)
            timing = res.data["timing"]
            self.assertIn("wall_s", timing)
            self.assertIn("perceive_s", timing)
            self.assertIn("verify_s", timing)

    @patch("kratos_agent.ccs.tasks.take_screenshot", return_value=(b"fake_png", "frame_123"))
    @patch("kratos_agent.ccs.tasks.compute_screen_diff", return_value=(False, 0)) # zero diff
    @patch("kratos_agent.ccs.tasks.detect_blockers", return_value=[])
    def test_computer_task_checkpoints_on_failure(self, mock_blockers, mock_diff, mock_screen):
        ccs = MockCCS(is_playing=False)
        assertion = OutcomeAssertion(kind="media_playing")

        with patch("kratos_agent.ccs.assertions.assertion_runner.run") as mock_assert_run:
            mock_assert_run.return_value = Evidence(
                claim="video is playing",
                method="cdp_js",
                met=False,
                observed={"paused": True},
                confidence=1.0,
                detail="video is paused",
            )
            res = computer_task("Play God of War", ccs, assertion=assertion)
            self.assertFalse(res.ok)
            checkpoints = res.data["checkpoints"]
            self.assertIn("PRE", checkpoints)
            self.assertIn("POST_FAIL", checkpoints)

if __name__ == "__main__":
    unittest.main()
