"""Unit tests for video playback verification and action idempotency (§12, §13, §14, §15, §16)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from kratos_agent.computer.browser.playwright import VideoPlaybackState, PlaywrightDriver
from kratos_agent.computer.browser.state_machine import BrowserActionRegistry, BrowserTaskState
from kratos_agent.computer.verifier import ActionVerifier, ComputerTaskResult


class TestVideoVerification(unittest.TestCase):
    def test_video_playback_state_properties(self) -> None:
        state_playing = VideoPlaybackState(
            video_present=True,
            paused=False,
            current_time=12.5,
            duration=3600.0,
            ready_state=4,
            visible=True,
            url="https://youtube.com/watch?v=xyz",
            title="GTA Vice City Walkthrough",
        )
        self.assertTrue(state_playing.is_playing)

        state_paused = VideoPlaybackState(
            video_present=True,
            paused=True,
            current_time=12.5,
            duration=3600.0,
            ready_state=4,
            visible=True,
            url="https://youtube.com/watch?v=xyz",
            title="GTA Vice City Walkthrough",
        )
        self.assertFalse(state_paused.is_playing)

        state_hidden = VideoPlaybackState(
            video_present=True,
            paused=False,
            current_time=12.5,
            duration=3600.0,
            ready_state=4,
            visible=False,
            url="https://youtube.com/watch?v=xyz",
            title="GTA Vice City Walkthrough",
        )
        self.assertFalse(state_hidden.is_playing)

    def test_action_idempotency_and_retry_budget(self) -> None:
        registry = BrowserActionRegistry()
        action_key = registry.compute_action_key(
            task_id="task_001",
            target_page_id="page_1",
            action_type="play_video",
            arguments={"query": "GTA Vice City"},
        )
        self.assertFalse(registry.was_successful(action_key))
        self.assertTrue(registry.can_retry(action_key))

        # Attempt 1
        attempts = registry.record_attempt(action_key)
        self.assertEqual(attempts, 1)
        self.assertTrue(registry.can_retry(action_key))

        # Attempt 2
        attempts = registry.record_attempt(action_key)
        self.assertEqual(attempts, 2)
        self.assertFalse(registry.can_retry(action_key))

        # Success record
        registry.record_success(action_key)
        self.assertTrue(registry.was_successful(action_key))

    def test_computer_task_result_contract(self) -> None:
        res = ComputerTaskResult(
            task_id="task_123",
            success=True,
            verified=True,
            target="Chrome",
            action_count=3,
            retries=0,
            evidence={"url": "https://youtube.com", "video_playing": True},
        )
        self.assertTrue(res.success)
        self.assertTrue(res.verified)
        self.assertEqual(res.evidence["video_playing"], True)


if __name__ == "__main__":
    unittest.main()
