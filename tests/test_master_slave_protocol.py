"""Unit tests for Master-Slave communication protocol, CommandBus, and correlation."""
import asyncio
import unittest

from kratos_agent.master.protocol import (
    CommandAction,
    CommandPriority,
    MasterCommand,
    SlaveAck,
    SlaveResult,
    CommandBus,
)
from kratos_agent.master.supervisor import MasterSupervisor


class TestMasterSlaveProtocol(unittest.TestCase):

    def test_command_serialization(self):
        cmd = MasterCommand.create(
            objective="Play GTA Vice City walkthrough on YouTube",
            action="browser.youtube.play",
            parameters={"query": "GTA Vice City walkthrough"},
            constraints={"reuse_existing_chrome_window": True, "create_one_task_tab": True},
            expected_result={"video_playing": True, "playback_advancing": True},
            priority="high",
            timeout=45.0,
        )

        d = cmd.to_dict()
        self.assertTrue(d["command_id"].startswith("CMD-"))
        self.assertTrue(d["task_id"].startswith("TASK-"))
        self.assertEqual(d["action"], "browser.youtube.play")
        self.assertEqual(d["priority"], "high")
        self.assertTrue(d["constraints"]["create_one_task_tab"])

        restored = MasterCommand.from_dict(d)
        self.assertEqual(restored.command_id, cmd.command_id)
        self.assertEqual(restored.task_id, cmd.task_id)
        self.assertEqual(restored.objective, cmd.objective)
        self.assertEqual(restored.parameters, cmd.parameters)

    def test_slave_ack_serialization(self):
        ack = SlaveAck(
            command_id="CMD-123",
            task_id="TASK-456",
            accepted=True,
            status="accepted",
        )
        d = ack.to_dict()
        self.assertEqual(d["type"], "ACK")
        self.assertTrue(d["accepted"])

        restored = SlaveAck.from_dict(d)
        self.assertEqual(restored.command_id, "CMD-123")
        self.assertTrue(restored.accepted)

    def test_slave_result_serialization(self):
        result = SlaveResult(
            command_id="CMD-123",
            task_id="TASK-456",
            status="success",
            verified=True,
            terminal=True,
            state="VIDEO_PLAYING",
            evidence={
                "tab": "PAGE-42",
                "video_present": True,
                "paused": False,
                "playback_advanced": True,
            },
        )
        self.assertTrue(result.is_success())
        d = result.to_dict()
        self.assertEqual(d["type"], "RESULT")
        self.assertEqual(d["state"], "VIDEO_PLAYING")

        restored = SlaveResult.from_dict(d)
        self.assertEqual(restored.command_id, "CMD-123")
        self.assertTrue(restored.verified)
        self.assertTrue(restored.is_success())

    def test_command_bus_enqueue_dequeue(self):
        async def _test():
            bus = CommandBus()
            cmd = MasterCommand.create(
                objective="Open Chrome",
                action="open_application",
                priority="normal",
            )
            ack_fut, res_fut = await bus.send_command(cmd)

            # Dequeue from slave side
            dequeued = await bus.get_next_command()
            self.assertEqual(dequeued.command_id, cmd.command_id)

            # Publish ACK
            ack = SlaveAck(command_id=cmd.command_id, task_id=cmd.task_id, accepted=True)
            await bus.publish_ack(ack)
            self.assertTrue(ack_fut.done())
            self.assertTrue((await ack_fut).accepted)

            # Publish Result
            res = SlaveResult(command_id=cmd.command_id, task_id=cmd.task_id, status="success", verified=True)
            await bus.publish_result(res)
            self.assertTrue(res_fut.done())
            self.assertTrue((await res_fut).verified)

        asyncio.run(_test())

    def test_command_priority_ordering(self):
        async def _test():
            bus = CommandBus()
            low_cmd = MasterCommand.create(objective="Low task", action="generic", priority="low")
            urgent_cmd = MasterCommand.create(objective="Urgent task", action="generic", priority="urgent")
            high_cmd = MasterCommand.create(objective="High task", action="generic", priority="high")

            await bus.send_command(low_cmd)
            await bus.send_command(urgent_cmd)
            await bus.send_command(high_cmd)

            # Dequeue order should be urgent -> high -> low
            first = await bus.get_next_command()
            self.assertEqual(first.command_id, urgent_cmd.command_id)

            second = await bus.get_next_command()
            self.assertEqual(second.command_id, high_cmd.command_id)

            third = await bus.get_next_command()
            self.assertEqual(third.command_id, low_cmd.command_id)

        asyncio.run(_test())

    def test_supervisor_response_formatting(self):
        sup = MasterSupervisor()

        # Success video
        r_vid = SlaveResult(command_id="C1", task_id="T1", status="success", verified=True, state="VIDEO_PLAYING")
        self.assertIn("video is playing", sup.format_response_for_master(r_vid).lower())

        # Failed
        r_fail = SlaveResult(command_id="C2", task_id="T2", status="failed", verified=False, error={"message": "Could not focus Chrome window."})
        self.assertIn("could not focus chrome", sup.format_response_for_master(r_fail).lower())


if __name__ == "__main__":
    unittest.main()
