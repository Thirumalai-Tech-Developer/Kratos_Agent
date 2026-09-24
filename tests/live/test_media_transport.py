"""Gemini Live media transport contract, exercised with a local fake session."""
import asyncio
from types import SimpleNamespace
import unittest

from kratos_agent.live.config import LiveConfig
from kratos_agent.live.events import LiveStatusHub
from kratos_agent.live.session import LiveSession
from kratos_agent.live.vision import VisionManager


def _session(model: str = "gemini-3.8-live-extended-thinking", **callbacks) -> LiveSession:
    return LiveSession(
        config=LiveConfig(api_key="test-key", model=model),
        out_queue=asyncio.Queue(),
        audio_manager=SimpleNamespace(audio_in_queue=asyncio.Queue()),
        router=SimpleNamespace(get_tool_declarations=lambda: []),
        status_hub=LiveStatusHub(),
        **callbacks,
    )


class LiveMediaTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_audio_and_jpeg_frames_are_sent_as_distinct_live_modalities(self):
        session = _session()
        session.is_running = True

        class FakeTransport:
            def __init__(self):
                self.calls = []

            async def send_realtime_input(self, **kwargs):
                self.calls.append(kwargs)
                if len(self.calls) == 2:
                    session.is_running = False

        transport = FakeTransport()
        session.session = transport
        await session.out_queue.put({"mime_type": "audio/pcm;rate=16000", "data": b"pcm"})
        await session.out_queue.put({"mime_type": "image/jpeg", "data": b"jpeg"})
        await session.out_queue.put({})

        await session.send_realtime()

        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(transport.calls[0]["audio"].mime_type, "audio/pcm;rate=16000")
        self.assertEqual(transport.calls[1]["video"].mime_type, "image/jpeg")

    async def test_audio_reply_and_transcript_reach_speaker_and_callback(self):
        transcripts = []
        user_transcripts = []
        session = _session(
            on_model_transcript=transcripts.append,
            on_user_transcript=user_transcripts.append,
        )
        session.is_running = True

        class FakeTransport:
            async def receive(self):
                yield SimpleNamespace(
                    tool_call=None,
                    server_content=SimpleNamespace(
                        interrupted=False,
                        model_turn=SimpleNamespace(parts=[SimpleNamespace(inline_data=SimpleNamespace(data=b"audio-out"))]),
                        output_transcription=SimpleNamespace(text="Hello there."),
                        input_transcription=SimpleNamespace(text="Can you hear me?"),
                        turn_complete=False,
                        interaction_status="IN_PROGRESS",
                    ),
                )
                session.is_running = False

        session.session = FakeTransport()
        await session.receive_loop()

        self.assertEqual(session.audio_manager.audio_in_queue.get_nowait(), b"audio-out")
        self.assertEqual(transcripts, ["Hello there."])
        self.assertEqual(user_transcripts, ["Can you hear me?"])

    def test_standard_live_model_omits_extended_thinking_level(self):
        standard = _session("gemini-3.8-live")._build_connect_config()
        extended = _session("gemini-3.8-live-extended-thinking")._build_connect_config()

        self.assertIsNone(standard.thinking_config)
        self.assertIsNotNone(extended.thinking_config)

    def test_video_capture_rate_is_capped_to_live_api_limit(self):
        vision = VisionManager(out_queue=asyncio.Queue(), mode="none", fps=30)
        self.assertEqual(vision.fps, 1.0)


if __name__ == "__main__":
    unittest.main()
