import tempfile
import unittest
from pathlib import Path
from kratos_agent.core.event_bus import EventBus
from kratos_agent.core.runtime_contracts import EventKind, RuntimeEvent
from kratos_agent.core.workspace_tracker import WorkspaceTracker
from kratos_agent.core.verification_manager import VerificationManager


class EventBusAndVerificationTests(unittest.TestCase):
    def test_event_bus_subscribe_and_publish(self):
        bus = EventBus()
        all_events = []
        task_events = []

        bus.subscribe(all_events.append)
        bus.subscribe(task_events.append, EventKind.TASK_STARTED)

        ev1 = RuntimeEvent(EventKind.TURN_STARTED, {"test": 1}, "turn1")
        ev2 = RuntimeEvent(EventKind.TASK_STARTED, {"title": "Build UI"}, "turn1")

        bus.publish(ev1)
        bus.publish(ev2)

        self.assertEqual(len(all_events), 2)
        self.assertEqual(len(task_events), 1)
        self.assertEqual(task_events[0].payload["title"], "Build UI")

    def test_workspace_tracker(self):
        tracker = WorkspaceTracker()
        tracker.record_file_created("src/App.tsx")
        tracker.record_file_modified("src/App.tsx")  # Modified after created -> remains created
        tracker.record_file_created("package.json")
        tracker.record_file_inspected("README.md")
        tracker.record_command("npm test", 0, "All tests passed")

        summary = tracker.summary()
        self.assertEqual(summary["created"], ["package.json", "src/App.tsx"])
        self.assertEqual(summary["inspected_count"], 1)
        self.assertEqual(summary["commands_count"], 1)

    def test_verification_manager_validates_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            ws = Path(tmp_dir)
            (ws / "valid.py").write_text("print('hello')\n", encoding="utf-8")
            (ws / "valid.json").write_text('{"name": "test"}', encoding="utf-8")
            (ws / "index.html").write_text('<!DOCTYPE html><html><body><h1>Spider-Man</h1></body></html>', encoding="utf-8")
            (ws / "invalid.py").write_text("def syntax_err(\n", encoding="utf-8")

            emitted = []
            vm = VerificationManager(ws, emit=emitted.append)

            # Valid files check
            res_valid = vm.verify_workspace(["valid.py", "valid.json", "index.html"])
            self.assertTrue(res_valid.passed)
            self.assertEqual(res_valid.files_checked, 3)

            # Invalid file check
            res_invalid = vm.verify_workspace(["invalid.py"])
            self.assertFalse(res_invalid.passed)
            self.assertTrue(any("SyntaxError" in d or "syntax error" in d for d in res_invalid.details))


if __name__ == "__main__":
    unittest.main()
