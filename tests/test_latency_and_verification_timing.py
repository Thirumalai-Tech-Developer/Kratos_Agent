import pathlib
import tempfile
import unittest
from kratos_agent.core.latency_tracker import LatencyTracker
from kratos_agent.core.planner import formulate_agent_plan
from kratos_agent.core.runtime_contracts import ModelResponse
from kratos_agent.core.verification_manager import VerificationManager


class LatencyAndVerificationTimingTests(unittest.TestCase):
    def test_latency_tracker_records_metrics(self):
        tracker = LatencyTracker()
        metrics = tracker.start_request(
            task_id="task_1",
            model="gemini-3.7-flash-high",
            provider="brain",
            context_tokens=1200,
            tools_count=15,
            history_messages=4,
            context_build_ms=15.2,
        )
        metrics.ttft_ms = 450.0
        metrics.generation_ms = 1200.0
        metrics.tool_execution_ms = 350.0
        metrics.total_ms = 1565.2
        metrics.output_tokens = 240
        tracker.record_completed(metrics)

        last = tracker.get_last_metrics()
        self.assertIsNotNone(last)
        self.assertEqual(last.task_id, "task_1")
        self.assertEqual(last.model, "gemini-3.7-flash-high")
        self.assertEqual(last.input_tokens, 1200)
        self.assertEqual(last.output_tokens, 240)
        self.assertGreater(last.total_ms, 1000)

        diag = last.format_diagnostic()
        self.assertIn("gemini-3.7-flash-high", diag)
        self.assertIn("1,200", diag)
        self.assertIn("Timing:", diag)

    def test_dynamic_plan_with_verification_metadata(self):
        mock_output = """{
  "goal": "Create a Ben 10 web application with modern React & TailwindCSS",
  "tasks": [
    {
      "id": "1",
      "title": "Scaffold React + Vite project with TailwindCSS",
      "verification": "build"
    },
    {
      "id": "2",
      "title": "Create alien database with stats and powers",
      "verification": "none"
    },
    {
      "id": "3",
      "title": "Implement Omnitrix dial and selection animations",
      "verification": "none"
    },
    {
      "id": "4",
      "title": "Build Alien Codex and details modal",
      "verification": "none"
    },
    {
      "id": "5",
      "title": "Develop Battle Arena and combat simulator",
      "verification": "none"
    },
    {
      "id": "6",
      "title": "Assemble main Ben 10 dashboard layout",
      "verification": "build"
    },
    {
      "id": "7",
      "title": "Verify transformation animations, battle logic, and build",
      "verification": "browser+build"
    }
  ]
}"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            ws = pathlib.Path(tmp_dir)
            model = type("M", (), {"complete": lambda self, req: ModelResponse(text=mock_output)})()
            plan = formulate_agent_plan(
                "create a ben 10 webapp using Modern UI React X TailwindCSS",
                model=model,
                workspace=ws,
            )

            self.assertIsNotNone(plan)
            self.assertEqual(len(plan.tasks), 7)
            # Intermediate implementation tasks should NOT be browser verification
            self.assertEqual(plan.tasks[0].verification, "build")
            self.assertEqual(plan.tasks[1].verification, "none")
            self.assertEqual(plan.tasks[2].verification, "none")
            # Dedicated final verification task has browser verification
            self.assertEqual(plan.tasks[6].verification, "browser+build")

    def test_non_web_tasks_do_not_have_browser_verification(self):
        mock_output = """{
  "goal": "Write Python Streamlit interface in interface.py",
  "tasks": [
    {"id": "1", "title": "Inspect Python dependencies", "verification": "none"},
    {"id": "2", "title": "Implement interface.py", "verification": "none"},
    {"id": "3", "title": "Validate Python syntax and execution", "verification": "build"}
  ]
}"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            ws = pathlib.Path(tmp_dir)
            model = type("M", (), {"complete": lambda self, req: ModelResponse(text=mock_output)})()
            plan = formulate_agent_plan(
                "write a python script with streamlit in interface.py",
                model=model,
                workspace=ws,
            )

            self.assertIsNotNone(plan)
            for t in plan.tasks:
                self.assertNotIn("browser", t.verification)

    def test_verification_manager_dedicated_stage(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            ws = pathlib.Path(tmp_dir)
            (ws / "main.py").write_text("print('hello world')", encoding="utf-8")
            (ws / "package.json").write_text('{"name": "test-app"}', encoding="utf-8")

            vm = VerificationManager(ws)
            res = vm.verify_workspace(["main.py", "package.json"], verification_type="build")
            self.assertTrue(res.passed)
            self.assertEqual(res.files_checked, 2)
            self.assertTrue(res.build_passed)
            self.assertIsNone(res.browser_passed)


if __name__ == "__main__":
    unittest.main()
