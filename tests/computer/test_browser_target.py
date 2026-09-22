"""Unit tests for BrowserTarget and BrowserTargetManager (§3)."""
from __future__ import annotations

import unittest

from kratos_agent.computer.browser.target import BrowserTarget, BrowserTargetManager


class TestBrowserTarget(unittest.TestCase):
    def setUp(self) -> None:
        self.mgr = BrowserTargetManager()

    def test_target_lifecycle(self) -> None:
        self.assertIsNone(self.mgr.get_active_target())

        target = BrowserTarget(
            browser_name="chrome",
            window_handle=12345,
            browser_pid=6789,
            url="https://www.youtube.com",
            title="YouTube",
            foreground=True,
            created_by_kratos=False,
        )
        self.mgr.set_active_target(target)

        active = self.mgr.get_active_target()
        self.assertIsNotNone(active)
        self.assertEqual(active.browser_name, "chrome")
        self.assertEqual(active.window_handle, 12345)
        self.assertEqual(active.url, "https://www.youtube.com")

        # Update target
        updated = self.mgr.update_target(url="https://www.youtube.com/watch?v=123", title="GTA Walkthrough")
        self.assertIsNotNone(updated)
        self.assertEqual(updated.url, "https://www.youtube.com/watch?v=123")
        self.assertEqual(updated.title, "GTA Walkthrough")

        # Resolve target
        resolved = self.mgr.resolve_target()
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.window_handle, 12345)

        # Clear target
        self.mgr.clear_target()
        self.assertIsNone(self.mgr.get_active_target())


if __name__ == "__main__":
    unittest.main()
