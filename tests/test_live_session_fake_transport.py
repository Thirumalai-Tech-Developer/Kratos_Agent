"""In-process LiveSession protocol test with a slow tool and fake Gemini transport.

It runs against the real LiveSession implementation. Optional Gemini SDK imports are
skipped only when the project's runtime dependencies are unavailable.
"""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock

try:
    from kratos_agent.live.config import LiveConfig
    from kratos_agent.live.events import LiveStatusHub
    from kratos_agent.live.session import LiveSession
    LIVE_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - environment dependent
    LiveSession = None
    LIVE_IMPORT_ERROR = exc


@unittest.skipIf(LIVE_IMPORT_ERROR is not None, f"Live runtime dependencies unavailable: {LIVE_IMPORT_ERROR}")
class LiveSessionAsyncToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_tool_does_not_block_receive_loop(self):
        second_response_seen = asyncio.Event()
        tool_finished = asyncio.Event()

        class FakeGeminiSession:
            def __init__(self):
                self.tool_responses = []

            async def receive(self):
                tool_call = SimpleNamespace(
                    function_calls=[SimpleNamespace(id="call-slow", name="observe", args={})]
                )
                yield SimpleNamespace(tool_call=tool_call, server_content=None)
                await asyncio.sleep(0.01)
                second_response_seen.set()
                yield SimpleNamespace(
                    tool_call=None,
                    server_content=SimpleNamespace(
                        interrupted=False,
                        model_turn=None,
                        output_transcription=None,
                        input_transcription=None,
                        turn_complete=False,
                        interaction_status="IN_PROGRESS",
                    ),
                )
                await asyncio.sleep(0.01)
                session.is_running = False

            async def send_tool_response(self, *, function_responses):
                self.tool_responses.extend(function_responses)

        async def slow_tool(_name, _args):
            await asyncio.sleep(0.15)
            tool_finished.set()
            return {"status": "success", "message": "observation complete"}

        router = MagicMock()
        router.handle_tool_call = slow_tool
        audio = SimpleNamespace(audio_in_queue=asyncio.Queue())
        session = LiveSession(
            config=LiveConfig(api_key="test-key", model="gemini-3.8-live-extended-thinking"),
            out_queue=asyncio.Queue(),
            audio_manager=audio,
            router=router,
            status_hub=LiveStatusHub(),
        )
        fake_transport = FakeGeminiSession()
        session.session = fake_transport
        session.is_running = True

        await session.receive_loop()
        self.assertTrue(second_response_seen.is_set(), "receive loop must process the next server event while tool runs")
        self.assertFalse(tool_finished.is_set(), "slow tool must still be running when the next event was received")

        await asyncio.gather(*session._pending_tool_tasks, return_exceptions=True)
        self.assertTrue(tool_finished.is_set())
        self.assertEqual(len(fake_transport.tool_responses), 1)
        self.assertEqual(fake_transport.tool_responses[0].id, "call-slow")
        self.assertEqual(fake_transport.tool_responses[0].response["status"], "success")


if __name__ == "__main__":
    unittest.main()
