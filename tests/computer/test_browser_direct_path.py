"""Unit tests for BrowserBackendSelector and direct browser routing."""
from __future__ import annotations
import unittest

from kratos_agent.computer.browser.selector import BrowserBackendSelector, BrowserBackendType
from kratos_agent.performance.router import RequestCategory, RequestRouter


class TestBrowserDirectPath(unittest.TestCase):
    def setUp(self) -> None:
        self.router = RequestRouter()

    def test_browser_backend_selector_prefers_playwright(self) -> None:
        backend = BrowserBackendSelector.select("Open YouTube in Chrome")
        # Should be either existing_session or playwright, never selenium
        self.assertIn(backend, (BrowserBackendType.PLAYWRIGHT, BrowserBackendType.EXISTING_SESSION, BrowserBackendType.GUI_ACCESSIBILITY))
        self.assertNotEqual(backend.value, "selenium")

    def test_open_youtube_routes_to_browser_fast_path(self) -> None:
        decision = self.router.classify("can you open youtube in chrome")
        self.assertEqual(decision.category, RequestCategory.BROWSER)
        self.assertTrue(decision.is_fast_path)
        self.assertFalse(decision.requires_planning)
        self.assertFalse(decision.requires_memory)
        self.assertIn("BROWSER", decision.target_tool_categories)

    def test_gta_vice_city_walkthrough_routes_to_browser_fast_path(self) -> None:
        decision = self.router.classify("can you open GTA Vice city walk through")
        self.assertEqual(decision.category, RequestCategory.BROWSER)
        self.assertTrue(decision.is_fast_path)
        self.assertFalse(decision.requires_planning)
        self.assertIn("BROWSER", decision.target_tool_categories)


if __name__ == "__main__":
    unittest.main()
