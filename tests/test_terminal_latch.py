import unittest
from kratos_agent.core.runtime_contracts import TerminalLatch

class MockAudit:
    def __init__(self):
        self.records = []
    def record(self, **kwargs):
        self.records.append(kwargs)

class TestTerminalLatch(unittest.TestCase):
    def test_single_terminal_status_allowed(self):
        latch = TerminalLatch()
        self.assertTrue(latch.try_set("task_1", "COMPLETED"))
        self.assertFalse(latch.try_set("task_1", "FAILED"))
        self.assertFalse(latch.try_set("task_1", "COMPLETED"))

    def test_non_terminal_always_allowed(self):
        latch = TerminalLatch()
        self.assertTrue(latch.try_set("task_1", "PENDING"))
        self.assertTrue(latch.try_set("task_1", "RUNNING"))
        self.assertTrue(latch.try_set("task_1", "RUNNING"))
        self.assertTrue(latch.try_set("task_1", "COMPLETED"))
        # Once COMPLETED, any further terminal status is refused
        self.assertFalse(latch.try_set("task_1", "FAILED"))

    def test_audit_recording_on_latch_violation(self):
        audit = MockAudit()
        latch = TerminalLatch(audit_recorder=audit)
        self.assertTrue(latch.try_set("task_abc", "FAILED"))
        self.assertFalse(latch.try_set("task_abc", "COMPLETED"))
        
        self.assertEqual(len(audit.records), 1)
        rec = audit.records[0]
        self.assertEqual(rec["kind"], "latch_violation")
        self.assertEqual(rec["task_id"], "task_abc")
        self.assertEqual(rec["first"], "FAILED")
        self.assertEqual(rec["refused"], "COMPLETED")

    def test_contradictory_sequence_impossible(self):
        # The observed sequence: "unfortunately the task..." (FAILED) -> "completed successfully" (COMPLETED)
        latch = TerminalLatch()
        first_result = latch.try_set("t_failed_then_succeed", "FAILED")
        second_result = latch.try_set("t_failed_then_succeed", "COMPLETED")
        self.assertTrue(first_result)
        self.assertFalse(second_result)

if __name__ == "__main__":
    unittest.main()
