"""Real in-process Master -> CommandBus -> Slave handoff regression test."""
import asyncio
import time
import unittest
from unittest.mock import patch

try:
    from kratos_agent.master.supervisor import MasterSupervisor
    from kratos_agent.master.protocol import SlaveResult
    from kratos_agent.slave.executor import SlaveExecutor
    IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - environment dependent
    IMPORT_ERROR = exc


@unittest.skipIf(IMPORT_ERROR is not None, f"Kratos runtime dependencies unavailable: {IMPORT_ERROR}")
class MasterSlaveWaitForResultTests(unittest.IsolatedAsyncioTestCase):
    async def test_wait_for_result_returns_verified_completion_not_started(self):
        supervisor = MasterSupervisor(session_id="LIVE-REAL-TEST")
        slave = SlaveExecutor()
        slave.start()

        async def verified_after_delay(cmd):
            await asyncio.sleep(0.08)
            return SlaveResult(
                command_id=cmd.command_id,
                task_id=cmd.task_id,
                status="success",
                verified=True,
                terminal=True,
                state="TEST_COMPLETE",
                evidence={"backend": "in_process_test", "verified": True},
            )

        try:
            with patch.object(slave, "_execute_command", side_effect=verified_after_delay):
                started = time.monotonic()
                result = await supervisor.submit_delegated_task(
                    objective="Run a deterministic verified mission",
                    action="generic_task",
                    wait_for_result=True,
                    timeout=5.0,
                )
                elapsed = time.monotonic() - started

            self.assertGreaterEqual(elapsed, 0.07)
            self.assertEqual(result["status"], "success")
            self.assertTrue(result["verified"])
            self.assertEqual(result["state"], "TEST_COMPLETE")
            self.assertNotEqual(result["status"], "started")
            self.assertFalse(supervisor.is_busy())
        finally:
            slave.stop()


if __name__ == "__main__":
    unittest.main()
