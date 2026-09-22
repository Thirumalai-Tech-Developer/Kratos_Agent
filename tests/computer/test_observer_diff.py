"""Tests for ComputerObserver state diffing."""
import unittest
from kratos_agent.computer.state import ComputerState
from kratos_agent.computer.observer import ComputerObserver


class TestObserverDiff(unittest.TestCase):
    def test_observer_compute_diff(self):
        observer = ComputerObserver()

        before = ComputerState(
            platform="windows",
            active_window={"id": "1", "title": "Editor"},
            windows=[{"id": "1", "title": "Editor"}],
            applications=[{"pid": 10, "name": "editor.exe"}],
            clipboard="old text",
            browser_state={"url": "https://example.com"},
        )

        after = ComputerState(
            platform="windows",
            active_window={"id": "2", "title": "Save As Dialog"},
            windows=[{"id": "1", "title": "Editor"}, {"id": "2", "title": "Save As Dialog"}],
            applications=[{"pid": 10, "name": "editor.exe"}],
            clipboard="new text",
            browser_state={"url": "https://example.com/saved"},
        )

        diff = observer.compute_diff(before, after)
        self.assertTrue(diff.state_changed)
        self.assertTrue(diff.active_window_changed)
        self.assertIn("Save As Dialog", diff.new_windows)
        self.assertTrue(diff.dialog_appeared)
        self.assertGreaterEqual(len(diff.changes), 3)


if __name__ == "__main__":
    unittest.main()
