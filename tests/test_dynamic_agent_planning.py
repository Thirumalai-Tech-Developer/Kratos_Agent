import pathlib
import tempfile
import unittest
from kratos_agent.core.planner import formulate_agent_plan
from kratos_agent.core.runtime_contracts import ModelResponse


class DynamicAgentPlanningTests(unittest.TestCase):
    def test_distinct_plans_generated_for_distinct_requests(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            ws = pathlib.Path(tmp_dir)

            # 1. Streamlit request
            streamlit_json = """{
  "goal": "Build Streamlit LLM interface in interface.py",
  "tasks": [
    {"id": "1", "title": "Inspect Python dependencies and Streamlit environment"},
    {"id": "2", "title": "Design Streamlit chat UI layout and state management in interface.py"},
    {"id": "3", "title": "Implement LLM client integration and message streaming"},
    {"id": "4", "title": "Verify interface.py syntax and Streamlit execution"}
  ]
}"""
            plan_streamlit = formulate_agent_plan(
                "write a python script to run llm interface with streamlit in interface.py file",
                model=type("M", (), {"complete": lambda self, req: ModelResponse(text=streamlit_json)})(),
                workspace=ws,
            )
            self.assertEqual(plan_streamlit.goal, "Build Streamlit LLM interface in interface.py")
            self.assertIn("interface.py", plan_streamlit.tasks[1].title)
            self.assertIn("Streamlit", plan_streamlit.tasks[0].title)

            # 2. Dark mode request
            dark_mode_json = """{
  "goal": "Add dark mode to React application",
  "tasks": [
    {"id": "1", "title": "Inspect React application and CSS theme setup"},
    {"id": "2", "title": "Define dark theme CSS custom properties and palette"},
    {"id": "3", "title": "Create ThemeToggle component with localStorage persistence"},
    {"id": "4", "title": "Apply dark mode styles across components and verify"}
  ]
}"""
            plan_dark = formulate_agent_plan(
                "add dark mode to my existing React application",
                model=type("M", (), {"complete": lambda self, req: ModelResponse(text=dark_mode_json)})(),
                workspace=ws,
            )
            self.assertEqual(plan_dark.goal, "Add dark mode to React application")
            self.assertIn("ThemeToggle", plan_dark.tasks[2].title)
            self.assertIn("CSS", plan_dark.tasks[1].title)

            # 3. Android Bug fix request
            android_json = """{
  "goal": "Fix login bug in Android application",
  "tasks": [
    {"id": "1", "title": "Inspect LoginActivity and auth network call flow"},
    {"id": "2", "title": "Diagnose token serialization/null pointer exception"},
    {"id": "3", "title": "Apply fix to login repository and error handling"},
    {"id": "4", "title": "Run unit tests and verify login flow"}
  ]
}"""
            plan_android = formulate_agent_plan(
                "fix the login bug in this Android application",
                model=type("M", (), {"complete": lambda self, req: ModelResponse(text=android_json)})(),
                workspace=ws,
            )
            self.assertEqual(plan_android.goal, "Fix login bug in Android application")
            self.assertIn("LoginActivity", plan_android.tasks[0].title)
            self.assertIn("token serialization", plan_android.tasks[1].title)

            # Ensure all plans are completely unique and non-generic
            self.assertNotEqual(plan_streamlit.goal, plan_dark.goal)
            self.assertNotEqual(plan_dark.goal, plan_android.goal)
            self.assertNotEqual(
                [t.title for t in plan_streamlit.tasks],
                [t.title for t in plan_dark.tasks],
            )
            self.assertNotEqual(
                [t.title for t in plan_dark.tasks],
                [t.title for t in plan_android.tasks],
            )


if __name__ == "__main__":
    unittest.main()
