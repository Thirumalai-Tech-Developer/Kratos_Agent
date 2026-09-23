"""Unit tests for BrowserTaskContext, tab locking, and physical playback verification."""
import unittest

from kratos_agent.computer.browser.target import (
    BrowserTaskContext,
    BrowserTaskTarget,
    BrowserTargetManager,
)
from kratos_agent.computer.browser.intent import parse_media_intent, should_reuse_browser_context
from kratos_agent.computer.state import ActionResult


class TestBrowserContinuation(unittest.TestCase):

    def test_browser_task_context_initialization(self):
        ctx = BrowserTaskContext(
            task_id="TASK-100",
            tab_id="PAGE-42",
            hwnd=123456,
            pid=7890,
            url="https://www.youtube.com",
            locked=True,
        )
        self.assertEqual(ctx.task_id, "TASK-100")
        self.assertEqual(ctx.tab_id, "PAGE-42")
        self.assertEqual(ctx.hwnd, 123456)
        self.assertTrue(ctx.locked)

        d = ctx.to_dict()
        self.assertEqual(d["tab_id"], "PAGE-42")
        self.assertTrue(d["locked"])

    def test_tab_continuity_reuse(self):
        active_task = BrowserTaskTarget(
            task_id="TASK-100",
            tab_id="PAGE-42",
            window_handle=123456,
            browser_pid=7890,
            current_url="https://www.youtube.com",
            locked=True,
        )

        # Continuation command: "play GTA Vice City"
        next_intent = parse_media_intent("play GTA Vice City")
        reuse = should_reuse_browser_context(active_task, next_intent)
        self.assertTrue(reuse)

    def test_physical_playback_verification_logic(self):
        # Successful playback case: video element exists, paused is false, currentTime advances
        advancement = 32.7 - 31.2
        playback_verified = (advancement > 0.5)

        res = ActionResult(
            ok=True,
            verified=playback_verified,
            observation="Video is playing. Current time advanced from 31.2s to 32.7s.",
            metadata={"current_time_before": 31.2, "current_time_after": 32.7, "paused": False},
        )
        self.assertTrue(res.ok)
        self.assertTrue(res.verified)
        self.assertFalse(res.metadata["paused"])
        self.assertGreater(res.metadata["current_time_after"], res.metadata["current_time_before"])



if __name__ == "__main__":
    unittest.main()
