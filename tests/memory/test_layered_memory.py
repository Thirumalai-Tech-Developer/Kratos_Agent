"""Unit tests for Memory Engine V2 layered architecture, ranking, and consolidation."""
from __future__ import annotations
import tempfile
import time
import unittest
from pathlib import Path

from kratos_agent.memory.models import (
    MemoryLayer,
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
)
from kratos_agent.memory.manager import MemoryManager
from kratos_agent.memory.ranking import rank_memories
from kratos_agent.memory.decay import apply_decay, reinforce_memory
from kratos_agent.memory.consolidation import deduplicate_records, consolidate_memories


class TestLayeredMemory(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.storage_path = Path(self.tmp_dir.name) / "test_memory.json"
        self.mm = MemoryManager()
        self.mm.store.storage_path = self.storage_path

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_working_memory(self) -> None:
        wm = self.mm.working
        wm.goal = "Build user login"
        wm.current_step = 1
        wm.active_application = "VS Code"
        wm.record_action("read_file", "Found auth.py", ok=True)

        self.assertEqual(wm.goal, "Build user login")
        self.assertEqual(len(wm.recent_actions), 1)
        self.assertEqual(wm.recent_actions[0]["action"], "read_file")

        wm.reset()
        self.assertEqual(wm.goal, "")
        self.assertEqual(len(wm.recent_actions), 0)

    def test_procedural_memory_workflows(self) -> None:
        wf = self.mm.save_workflow(
            name="GitHub create issue",
            trigger="create github issue",
            steps=["open repo", "open issues", "click new issue", "fill title", "submit"],
            application="Chrome",
        )
        self.assertEqual(wf.name, "GitHub create issue")
        self.assertEqual(len(wf.steps), 5)

        retrieved = self.mm.get_workflow("create github issue")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, "GitHub create issue")

    def test_application_and_error_memory(self) -> None:
        # App knowledge
        self.mm.application.add_fact("VS Code", "Integrated terminal opens with Ctrl+`")
        self.mm.application.add_shortcut("VS Code", "open_terminal", "ctrl+`")
        app_know = self.mm.application.get_knowledge("VS Code")
        self.assertIsNotNone(app_know)
        self.assertIn("Integrated terminal opens with Ctrl+`", app_know.facts)

        # Error recovery
        self.mm.errors.record_solution(
            error="Playwright browser executable missing",
            solution="Run playwright install chromium",
            context="Windows",
        )
        sol = self.mm.errors.find_solution("Playwright browser executable missing")
        self.assertIsNotNone(sol)
        self.assertEqual(sol.solution, "Run playwright install chromium")

    def test_hybrid_ranking(self) -> None:
        r1 = MemoryRecord(content="Playwright is used for browser automation", importance=0.9, confidence=0.95)
        r2 = MemoryRecord(content="Kratos uses Python 3.14", importance=0.5, confidence=0.8)
        r3 = MemoryRecord(content="Unrelated recipe for baking cookies", importance=0.1, confidence=0.2)

        q = MemoryQuery(text="browser automation with playwright", limit=2)
        ranked = rank_memories(q, [r1, r2, r3])

        self.assertGreater(len(ranked), 0)
        # r1 should be top-ranked
        self.assertEqual(ranked[0][0].content, r1.content)

    def test_memory_decay_and_reinforcement(self) -> None:
        rec = MemoryRecord(content="Fact", importance=0.8, confidence=0.8, layer=MemoryLayer.EPISODIC)
        initial_conf = rec.confidence

        # Apply 10 days decay
        apply_decay(rec, elapsed_days=10.0)
        self.assertLess(rec.confidence, initial_conf)

        # Reinforce on successful reuse
        conf_before = rec.confidence
        reinforce_memory(rec, success=True, bonus=0.15)
        self.assertGreater(rec.confidence, conf_before)
        self.assertEqual(rec.success_count, 2)

    def test_memory_deduplication_and_consolidation(self) -> None:
        r1 = MemoryRecord(content="Kratos is implemented in Python", confidence=0.8)
        r2 = MemoryRecord(content="kratos is implemented in python!", confidence=0.9)
        r3 = MemoryRecord(content="Tiny", confidence=0.1, importance=0.1)  # Low confidence/importance

        deduped = deduplicate_records([r1, r2])
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0].confidence, 0.9)  # Kept higher confidence

        consolidated = consolidate_memories([r1, r2, r3], min_confidence=0.20)
        self.assertEqual(len(consolidated), 1)

    def test_compact_context_output(self) -> None:
        self.mm.remember("Playwright is used for browser automation", importance=0.9, confidence=0.95)
        self.mm.remember("VS Code terminal shortcut is Ctrl+`", importance=0.8, confidence=0.9)

        ctx = self.mm.get_compact_context("browser automation", limit=3)
        self.assertIsInstance(ctx, list)
        self.assertLessEqual(len(ctx), 3)
        self.assertTrue(any("Playwright" in c for c in ctx))


if __name__ == "__main__":
    unittest.main()
