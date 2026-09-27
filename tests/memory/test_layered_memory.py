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

    def test_fuzzy_semantic_deduplication(self) -> None:
        r1 = MemoryRecord(content="Always use uv pip install to add dependencies", layer=MemoryLayer.SEMANTIC)
        r2 = MemoryRecord(content="Use uv pip install for adding project dependencies", layer=MemoryLayer.SEMANTIC)
        deduped = deduplicate_records([r1, r2], fuzzy_threshold=0.75)
        self.assertEqual(len(deduped), 1)

    def test_cache_telemetry(self) -> None:
        self.mm.remember("FastAPI server runs on port 8000", importance=0.8, confidence=0.9)
        # First query: cache miss
        _ = self.mm.recall("FastAPI server")
        # Second identical query: cache hit
        _ = self.mm.recall("FastAPI server")

        stats = self.mm.store.get_cache_stats()
        self.assertGreaterEqual(stats["hits"], 1)
        self.assertGreaterEqual(stats["misses"], 1)
        self.assertGreater(stats["hit_rate_pct"], 0.0)

    def test_export_and_import_memory(self) -> None:
        self.mm.remember("Unique exported fact about quantum computing", importance=0.9, confidence=0.95)
        export_file = Path(self.tmp_dir.name) / "exported_mem.json"
        saved = self.mm.export_memory(export_file)
        self.assertTrue(saved.exists())

        # Create fresh MemoryManager and import
        new_mm = MemoryManager()
        new_mm.store.storage_path = Path(self.tmp_dir.name) / "new_mem.json"
        imported_count = new_mm.import_memory(saved)
        self.assertGreaterEqual(imported_count, 1)
        recalled = new_mm.recall("quantum computing")
        self.assertTrue(any("quantum computing" in r.content for r in recalled))

    def test_memory_optimizer_full_maintenance(self) -> None:
        from kratos_agent.memory.maintenance import MemoryOptimizer
        opt = MemoryOptimizer(memory_store=self.mm.store)

        # Seed working and episodic records
        self.mm.store.add(MemoryRecord(content="Ephemeral task step", layer=MemoryLayer.WORKING, importance=0.05, confidence=0.05))
        self.mm.store.add(MemoryRecord(content="Permanent architecture rule", layer=MemoryLayer.SEMANTIC, importance=0.9, confidence=0.9, tags=["permanent"]))

        report = opt.run_maintenance(min_confidence=0.20, optimize_db=True, optimize_sessions=False)
        self.assertIsNotNone(report)
        self.assertGreater(report.duration_ms, 0.0)
        self.assertIn(report.health_status, ("OPTIMAL", "HEALTHY", "NEEDS_OPTIMIZATION"))
        self.assertGreaterEqual(report.health_score, 0.0)


if __name__ == "__main__":
    unittest.main()
