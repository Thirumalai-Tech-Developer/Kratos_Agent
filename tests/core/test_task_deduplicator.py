"""Unit tests for TaskDeduplicator (§30)."""
from __future__ import annotations

import time
import unittest

from kratos_agent.core.task_deduplicator import TaskDeduplicator


class TestTaskDeduplicator(unittest.TestCase):
    def setUp(self) -> None:
        self.dedup = TaskDeduplicator(window_seconds=1.0)

    def test_task_normalization(self) -> None:
        n1 = self.dedup.normalize_task("Can you open YouTube?")
        n2 = self.dedup.normalize_task("  can you open youtube  ")
        n3 = self.dedup.normalize_task("can, you open: youtube!")
        self.assertEqual(n1, "can you open youtube")
        self.assertEqual(n2, "can you open youtube")
        self.assertEqual(n3, "can you open youtube")

    def test_duplicate_rejection_within_window(self) -> None:
        # First arrival -> not duplicate
        self.assertFalse(self.dedup.is_duplicate("Can you open YouTube?"))

        # Immediate repeated arrival -> duplicate!
        self.assertTrue(self.dedup.is_duplicate("can you open youtube"))
        self.assertTrue(self.dedup.is_duplicate("can you open youtube?"))

        # Different task -> not duplicate
        self.assertFalse(self.dedup.is_duplicate("play GTA Vice City walkthrough"))

        # After window expires -> allowed again
        time.sleep(1.1)
        self.assertFalse(self.dedup.is_duplicate("Can you open YouTube?"))


if __name__ == "__main__":
    unittest.main()
