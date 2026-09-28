"""Gemini Live is a speech-output device; Kratos owns all user-facing reasoning."""
import asyncio
from types import SimpleNamespace
import unittest

from kratos_agent.live.config import LiveConfig
from kratos_agent.live.events import LiveStatusHub
from kratos_agent.live.session import LiveSession, SPEECH_SYSTEM_PROMPT
from kratos_agent.live.vision import VisionManager


def _session(model: str = "gemini-3.8-live") -> LiveSession:
    return LiveSession(
        config=LiveConfig(api_key="test-key", model=model),
        out_queue=asyncio.Queue(),
        audio_manager=SimpleNamespace(audio_in_queue=asyncio.Queue()),
        status_hub=LiveStatusHub(),
    )


class LiveMediaTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_speech_request_is_the_only_text_sent_to_gemini(self):
        session = _session()
        session.is_running = True

        class FakeTransport:
            def __init__(self):
                self.sent = []

            async def send(self, **kwargs):
                self.sent.append(kwargs)

        transport = FakeTransport()
        session.session = transport
        await session.speak_text("Hello from Kratos.")

        self.assertEqual(len(transport.sent), 1)
        sent = transport.sent[0]["input"]
        self.assertIn("Render only the following approved phrase", sent)
        self.assertIn("Hello from Kratos.", sent)

    async def test_audio_output_reaches_speaker_and_input_or_tools_are_ignored(self):
        transcripts = []
        session = _session()
        session.on_model_transcript = transcripts.append
        session.is_running = True

        class FakeTransport:
            async def receive(self):
                yield SimpleNamespace(
                    tool_call=SimpleNamespace(function_calls=[SimpleNamespace(name="execute_mission")]),
                    server_content=SimpleNamespace(
                        model_turn=SimpleNamespace(parts=[SimpleNamespace(inline_data=SimpleNamespace(data=b"audio-out"))]),
                        output_transcription=SimpleNamespace(text="Hello there."),
                        input_transcription=SimpleNamespace(text="run a task"),
                        turn_complete=False,
                    ),
                )
                session.is_running = False

        session.session = FakeTransport()
        await session.receive_loop()

        self.assertEqual(session.audio_manager.audio_in_queue.get_nowait(), b"audio-out")
        self.assertEqual(transcripts, ["Hello there."])
        self.assertNotIn("input_transcription", session.get_diagnostics())

    def test_connection_config_has_no_tool_or_input_audio_surface(self):
        config = _session()._build_connect_config()
        self.assertIn("only job is to speak", SPEECH_SYSTEM_PROMPT)
        self.assertEqual(config.response_modalities, ["AUDIO"])
        self.assertFalse(getattr(config, "tools", None))
        self.assertIsNone(getattr(config, "input_audio_transcription", None))

    def test_media_queue_is_not_a_gemini_input_transport(self):
        session = _session()
        self.assertFalse(hasattr(session, "send_realtime"))

    def test_video_capture_rate_is_capped_for_local_capture(self):
        vision = VisionManager(out_queue=asyncio.Queue(), mode="none", fps=30)
        self.assertEqual(vision.fps, 1.0)


if __name__ == "__main__":
    unittest.main()
