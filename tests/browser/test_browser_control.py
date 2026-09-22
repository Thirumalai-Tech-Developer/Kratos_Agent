"""Tests for BrowserManager and PlaywrightDriver."""
import unittest
from kratos_agent.computer.browser.manager import BrowserManager
from kratos_agent.computer.browser.playwright import PlaywrightDriver


class TestBrowserControl(unittest.TestCase):
    def test_browser_manager_state(self):
        bm = BrowserManager()
        state = bm.get_state()
        self.assertIsInstance(state, dict)
        self.assertIn("connected", state)
        self.assertIn("url", state)

    def test_playwright_driver_interface(self):
        drv = PlaywrightDriver()
        self.assertTrue(hasattr(drv, "click"))
        self.assertTrue(hasattr(drv, "fill"))
        self.assertTrue(hasattr(drv, "dump_interactive_dom"))
        # If not connected, returns graceful ActionResult
        res = drv.click(role="button", name="NonExistent")
        self.assertFalse(res.ok)


if __name__ == "__main__":
    unittest.main()
