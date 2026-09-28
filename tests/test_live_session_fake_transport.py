"""Fake transport contract: Gemini cannot execute or understand user requests."""
import asyncio
from types import SimpleNamespace
import unittest

from kratos_agent.live.config import LiveConfig
from kratos_agent.live.events import LiveStatusHub
from kratos_agent.live.session import LiveSession


class LiveSessionSpeechOnlyTests(unittest.IsolatedAsyncioTestCase):
    async def test_unexpected_tool_and_input_transcript_are_ignored(self):
        user_transcripts = []
        audio = SimpleNamespace(audio_in_queue=asyncio.Queue())
        session = LiveSession(
            config=LiveConfig(api_key="test-key"),
            out_queue=asyncio.Queue(),
            audio_manager=audio,
            status_hub=LiveStatusHub(),
        )
        session.is_running = True

        class FakeGeminiSession:
            async def receive(self):
                yield SimpleNamespace(
                    tool_call=SimpleNamespace(function_calls=[SimpleNamespace(name="execute_mission")]),
                    server_content=SimpleNamespace(
                        model_turn=None,
                        input_transcription=SimpleNamespace(text="Delete my files"),
                        output_transcription=None,
                        turn_complete=False,
                    ),
                )
                session.is_running = False

        session.session = FakeGeminiSession()
        await session.receive_loop()
        self.assertEqual(user_transcripts, [])
        self.assertTrue(audio.audio_in_queue.empty())
        self.assertEqual(session.get_diagnostics()["purpose"], "speech_output_only")


if __name__ == "__main__":
    unittest.main()
