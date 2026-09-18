import unittest
from kratos_agent.core.task_manager import ExecutionPlan, TaskItem, TaskState


class TaskManagerTests(unittest.TestCase):
    def test_task_state_glyphs_and_styles(self):
        self.assertEqual(TaskState.PENDING.glyph, "☐")
        self.assertEqual(TaskState.RUNNING.glyph, "⠋")
        self.assertEqual(TaskState.COMPLETED.glyph, "✓")
        self.assertEqual(TaskState.FAILED.glyph, "✗")
        self.assertEqual(TaskState.SKIPPED.glyph, "⊘")
        self.assertEqual(TaskState.NEEDS_ATTENTION.glyph, "⚠")

    def test_task_item_lifecycle(self):
        task = TaskItem(id="t1", title="Analyze project")
        self.assertEqual(task.state, TaskState.PENDING)

        task.start()
        self.assertEqual(task.state, TaskState.RUNNING)
        self.assertIsNotNone(task.started_at)

        task.add_file("src/App.tsx")
        task.add_file("src/App.tsx")  # Deduplication
        self.assertEqual(task.files_affected, ["src/App.tsx"])

        task.complete("Finished in 1s")
        self.assertEqual(task.state, TaskState.COMPLETED)
        self.assertEqual(task.detail, "Finished in 1s")
        self.assertIsNotNone(task.finished_at)

    def test_execution_plan_dynamic_operations(self):
        plan = ExecutionPlan(title="Spider-Man Plan")
        plan.set_tasks_from_titles([
            "Analyze project structure",
            "Create Spider-Man UI",
            "Run tests",
        ])
        self.assertEqual(plan.total_count, 3)
        self.assertEqual(plan.completed_count, 0)
        self.assertEqual(plan.progress_percent, 0)

        # Start step 1
        plan.start_task(0)
        self.assertEqual(plan.tasks[0].state, TaskState.RUNNING)

        # Complete step 1
        plan.complete_task(0)
        self.assertEqual(plan.tasks[0].state, TaskState.COMPLETED)
        self.assertEqual(plan.completed_count, 1)
        self.assertEqual(plan.progress_percent, 33)

        # Dynamically insert a newly discovered subtask
        inserted = plan.insert_task(1, "Configure WebGL canvas shader")
        self.assertEqual(plan.total_count, 4)
        self.assertEqual(plan.tasks[1].title, "Configure WebGL canvas shader")
        # Ensure completed history was preserved
        self.assertEqual(plan.tasks[0].state, TaskState.COMPLETED)

        # Fail step
        plan.fail_task("task_3", "SyntaxError in index.js")
        self.assertEqual(plan.tasks[3].state, TaskState.FAILED)
        self.assertEqual(plan.tasks[3].detail, "SyntaxError in index.js")

    def test_plan_serialization_roundtrip(self):
        plan = ExecutionPlan(title="Test Plan")
        plan.set_tasks_from_titles(["Step A", "Step B"])
        plan.start_task(0)
        plan.complete_task(0, "Done")

        data = plan.to_dict()
        self.assertEqual(data["title"], "Test Plan")
        self.assertEqual(len(data["tasks"]), 2)

        restored = ExecutionPlan.from_dict(data)
        self.assertEqual(restored.title, "Test Plan")
        self.assertEqual(len(restored.tasks), 2)
        self.assertEqual(restored.tasks[0].state, TaskState.COMPLETED)
        self.assertEqual(restored.tasks[0].detail, "Done")
        self.assertEqual(restored.tasks[1].state, TaskState.PENDING)


if __name__ == "__main__":
    unittest.main()
