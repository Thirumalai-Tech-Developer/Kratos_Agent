"""Unit tests for FocusPolicy and foreground enforcement (§8, §25, §26)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from kratos_agent.computer.apps.focus_policy import FocusPolicy
from kratos_agent.computer.apps.focus import focus_window, restore_previous_window
from kratos_agent.computer.gui.models import WindowInfo


class TestFocusPolicy(unittest.TestCase):
    def test_focus_policy_enum(self) -> None:
        self.assertEqual(FocusPolicy.KEEP_CURRENT.value, "keep_current")
        self.assertEqual(FocusPolicy.FOCUS_TARGET.value, "focus_target")
        self.assertEqual(FocusPolicy.RESTORE_PREVIOUS.value, "restore_previous")

    def test_keep_current_policy_bypasses_focus_switch(self) -> None:
        # KEEP_CURRENT should immediately succeed without switching focus
        res = focus_window(window_handle=99999, policy=FocusPolicy.KEEP_CURRENT)
        self.assertTrue(res)

    @patch("kratos_agent.computer.apps.focus.get_window_manager")
    @patch("kratos_agent.computer.apps.focus.get_active_window")
    def test_focus_target_with_verification(self, mock_get_active, mock_get_wm) -> None:
        # Mock active window returning target handle
        mock_win = WindowInfo(
            id="12345",
            title="Google Chrome",
            app_name="chrome.exe",
            is_active=True,
            bounds={"x": 0, "y": 0, "w": 800, "h": 600},
        )
        mock_get_active.return_value = mock_win
        mock_wm = MagicMock()
        mock_wm.focus_window.return_value = MagicMock(ok=True)
        mock_get_wm.return_value = mock_wm

        success = focus_window(window_handle="12345", policy=FocusPolicy.FOCUS_TARGET)
        self.assertTrue(success)
        mock_wm.focus_window.assert_called_with(handle="12345")


if __name__ == "__main__":
    unittest.main()
