"""End-to-end integration test for Gemini Live Master + OmniRoute Slave execution."""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from kratos_agent.master.protocol import (
    CommandAction,
    MasterCommand,
    SlaveAck,
    SlaveResult,
    get_command_bus,
)
from kratos_agent.master.supervisor import MasterSupervisor
from kratos_agent.slave.executor import SlaveExecutor


class TestMasterSlaveEndToEnd(unittest.TestCase):

    def setUp(self):
        self.bus = get_command_bus()
        self.supervisor = MasterSupervisor(session_id="LIVE-TEST-01")
        self.slave = SlaveExecutor()

    def tearDown(self):
        self.slave.stop()

    def test_e2e_youtube_play_delegation_and_verification(self):
        async def _run():
            # Start slave background executor
            self.slave.start()

            spoken_outputs = []
            self.supervisor.set_speech_callback(lambda txt: spoken_outputs.append(txt))

            # Master delegates YouTube play task
            with patch("kratos_agent.computer.browser.playwright.PlaywrightDriver") as mock_drv_cls:
                mock_drv = MagicMock()
                mock_drv_cls.return_value = mock_drv

                from kratos_agent.computer.state import ActionResult
                mock_drv.search_and_play_youtube.return_value = ActionResult(
                    ok=True,
                    verified=True,
                    observation="Playing video. Playback advanced from 10.0 to 12.0s.",
                    metadata={"url": "https://www.youtube.com/watch?v=123", "current_time_before": 10.0, "current_time_after": 12.0},
                )

                sub_res = await self.supervisor.submit_delegated_task(
                    objective="Play GTA Vice City walkthrough on YouTube",
                    action="browser.youtube.play",
                    parameters={"query": "GTA Vice City walkthrough"},
                    constraints={"reuse_existing_chrome_window": True, "create_one_task_tab": True},
                    expected_result={"video_playing": True, "playback_advancing": True},
                    wait_for_result=True,
                )

                self.assertTrue(sub_res["accepted"])
                self.assertEqual(sub_res["status"], "success")
                self.assertTrue(sub_res["verified"])
                self.assertEqual(sub_res["state"], "VIDEO_PLAYING")
                self.assertEqual(sub_res["evidence"]["query"], "GTA Vice City walkthrough")

                # Live missions return the verified result directly instead of
                # re-entering Gemini with a concurrent narration turn.
                self.assertEqual(spoken_outputs, [])

        asyncio.run(_run())

    def test_e2e_search_delegation(self):
        async def _run():
            self.slave.start()
            spoken_outputs = []
            self.supervisor.set_speech_callback(lambda txt: spoken_outputs.append(txt))

            from kratos_agent.search.models import SearchResponse, SearchResult
            mock_resp = SearchResponse(
                query="latest Python version",
                results=[
                    SearchResult(
                        title="Python 3.14 Release",
                        url="https://python.org",
                        snippet="Latest version is Python 3.14",
                        source="mock",
                        rank=1,
                    )
                ],
                total_results=1,
                provider="mock",
                latency_ms=2.0,
                citations=[],
            )

            with patch("kratos_agent.search.get_search_router") as mock_get_router:
                mock_router = MagicMock()
                async def _mock_search(*args, **kwargs):
                    return mock_resp
                mock_router.search = _mock_search
                mock_get_router.return_value = mock_router

                sub_res = await self.supervisor.submit_delegated_task(
                    objective="What is the latest Python version?",
                    action="search",
                    parameters={"query": "latest Python version", "mode": "fast"},
                )
                self.assertTrue(sub_res["accepted"])
                await asyncio.sleep(0.3)

                # Task should complete
                self.assertFalse(self.supervisor.is_busy())

        asyncio.run(_run())

    def test_e2e_cancellation(self):
        async def _run():
            self.slave.start()

            # Mock slow execution to test cancellation cleanly without live LLM calls
            with patch.object(self.slave, "_execute_command") as mock_exec:
                async def _slow_cmd(cmd):
                    await asyncio.sleep(5.0)
                    return SlaveResult(command_id=cmd.command_id, task_id=cmd.task_id, status="success", verified=True)
                mock_exec.side_effect = _slow_cmd

                # Submit task
                sub_res = await self.supervisor.submit_delegated_task(
                    objective="Long running data scrape",
                    action="generic_task",
                    timeout=30.0,
                )
                self.assertTrue(self.supervisor.is_busy())

                # Cancel task
                cancel_res = await self.supervisor.cancel_active_task(reason="User said abort")
                self.assertEqual(cancel_res["status"], "cancelled")
                self.assertFalse(self.supervisor.is_busy())

        asyncio.run(_run())

    def test_bridge_forwards_wait_for_result(self):
        async def _run():
            from kratos_agent.live.bridge import KratosBridge
            from kratos_agent.live.events import LiveStatusHub

            runtime = MagicMock()
            bridge = KratosBridge(runtime=runtime, status_hub=LiveStatusHub())
            bridge.slave_executor._running = True
            bridge.supervisor = MagicMock()
            bridge.supervisor.submit_delegated_task = AsyncMock(return_value={
                "status": "success", "task_id": "task-1", "capability": "generic_task"
            })

            res = await bridge.submit_task(
                "create a spiderman website in Documents",
                action="generic_task",
                wait_for_result=True,
            )

            self.assertEqual(res["status"], "success")
            bridge.supervisor.submit_delegated_task.assert_awaited_once()
            kwargs = bridge.supervisor.submit_delegated_task.await_args.kwargs
            self.assertTrue(kwargs["wait_for_result"])
            self.assertGreaterEqual(kwargs["timeout"], 600.0)

        asyncio.run(_run())

    def test_bridge_exposes_slave_failure_in_live_status(self):
        async def _run():
            from kratos_agent.live.bridge import KratosBridge
            from kratos_agent.live.events import LiveStatusHub

            hub = LiveStatusHub()
            bridge = KratosBridge(runtime=MagicMock(), status_hub=hub)
            bridge.slave_executor._running = True
            bridge.supervisor = MagicMock()
            bridge.supervisor.submit_delegated_task = AsyncMock(return_value={
                "status": "failed",
                "task_id": "task-auth-failure",
                "error": {
                    "component": "SlaveExecutor",
                    "stage": "physical_execution",
                    "message": "Model request failed: Brain access error (HTTP 401): Invalid API key",
                },
            })

            result = await bridge.submit_task("create and test calculator.py", wait_for_result=True)

            self.assertEqual(result["status"], "failed")
            self.assertEqual(hub.status.last_error_component, "slaveexecutor")
            self.assertIn("HTTP 401", hub.status.last_error)
            self.assertIn("Invalid API key", hub.status.last_error)
            bridge.supervisor.get_status.return_value = {
                "status": "failed",
                "last_error": {
                    "component": "brain",
                    "stage": "model_request",
                    "message": "Model request failed: Brain access error (HTTP 401): Invalid API key",
                    "recovery_action": "Correct the configured provider credential, then retry.",
                },
            }
            status = bridge.get_status()
            self.assertIn("HTTP 401", status["diagnostic_summary"])
            self.assertIn("Correct the configured provider credential", status["diagnostic_summary"])

        asyncio.run(_run())

    def test_agent_task_returns_structured_provider_failure(self):
        async def _run():
            runtime = MagicMock()
            runtime.run_agent.return_value = "Model request failed: Brain access error (HTTP 401): Invalid API key"
            slave = SlaveExecutor(runtime=runtime)
            cmd = MasterCommand.create(
                objective="Create and test calculator.py",
                action="generic_task",
                request_id="request-auth-failure",
            )

            result = await slave._execute_agent_task(cmd)

            self.assertEqual(result.status, "failed")
            self.assertFalse(result.verified)
            self.assertEqual(result.error["component"], "brain")
            self.assertEqual(result.error["stage"], "model_request")
            self.assertFalse(result.error["retryable"])
            self.assertIn("HTTP 401", result.error["message"])
            self.assertIn("OmniRoute credential was rejected", result.error["recovery_action"])

        asyncio.run(_run())

if __name__ == "__main__":
    unittest.main()
