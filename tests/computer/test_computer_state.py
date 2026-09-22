"""Tests for ComputerState, ComputerAction, and ActionResult serialization."""
import unittest
from kratos_agent.computer.state import ComputerState, ComputerAction, ActionResult, ObservationDiff
from kratos_agent.computer.gui.models import GUIElement, Rect, Point, StaleElementTracker


class TestComputerState(unittest.TestCase):
    def test_computer_state_to_dict_and_summary(self):
        state = ComputerState(
            platform="windows",
            desktop="main",
            active_window={"id": "123", "title": "Notepad - Untitled"},
            windows=[{"id": "123", "title": "Notepad - Untitled"}],
            applications=[{"pid": 456, "name": "notepad.exe"}],
            clipboard="hello world",
            screen_size=(1920, 1080),
            browser_state={"connected": False},
            capabilities={"gui": True},
            interactive_elements=[{"id": "uia_1", "role": "button", "name": "File"}],
            generation=2,
        )
        d = state.to_dict()
        self.assertEqual(d["platform"], "windows")
        self.assertEqual(d["active_window"]["title"], "Notepad - Untitled")
        self.assertEqual(d["interactive_elements_count"], 1)
        self.assertEqual(d["generation"], 2)

        summary = state.compact_summary()
        self.assertIn("Notepad - Untitled", summary)
        self.assertIn("gen=2", summary)

    def test_gui_element_rect_and_stale(self):
        elem = GUIElement(
            id="e1",
            name="Submit",
            role="button",
            bounds={"x": 100, "y": 200, "w": 80, "h": 30},
            generation=1,
        )
        self.assertIsNotNone(elem.rect)
        self.assertEqual(elem.rect.x, 100)
        self.assertEqual(elem.center, Point(140, 215))

        tracker = StaleElementTracker()
        self.assertFalse(tracker.is_stale(elem))

        # Advance generation
        tracker.advance_generation()
        self.assertTrue(tracker.is_stale(elem))

    def test_computer_action_serialization(self):
        action = ComputerAction(
            action="click",
            target={"name": "Save", "role": "button"},
            parameters={"button": "left"},
            expected_state={"dialog_closed": True},
            timeout=5.0,
        )
        d = action.to_dict()
        self.assertEqual(d["action"], "click")
        self.assertEqual(d["target"]["name"], "Save")
        self.assertTrue(d["expected_state"]["dialog_closed"])
        self.assertEqual(d["timeout"], 5.0)


if __name__ == "__main__":
    unittest.main()
