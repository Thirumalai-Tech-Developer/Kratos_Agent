"""Opt-in real Gemini Live speech-output smoke test.

Run on a real Kratos host with Python 3.14+ and Gemini credentials:
    KRATOS_RUN_LIVE_TESTS=1 pytest -q tests/test_live_real_smoke.py -s

The smoke test sends an approved phrase and checks that Gemini returns playable
PCM audio. It does not send microphone, camera, screen, or tool input.
"""
import asyncio
import os
from types import SimpleNamespace
import time
import unittest


@unittest.skipUnless(
    os.getenv("KRATOS_RUN_LIVE_TESTS") == "1",
    "Set KRATOS_RUN_LIVE_TESTS=1 to run the opt-in network smoke test",
)
class RealGeminiLiveSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_gemini_live_audio_roundtrip(self):
        from kratos_agent.live.config import LiveConfig
        from kratos_agent.live.events import LiveStatusHub
        from kratos_agent.live.session import LiveSession

        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            self.skipTest("Gemini API key is not configured")

        status = LiveStatusHub()
        audio = SimpleNamespace(audio_in_queue=asyncio.Queue())
        live = LiveSession(
            config=LiveConfig(
                api_key=api_key,
                enabled=True,
                model=os.getenv("KRATOS_LIVE_MODEL", "gemini-3.8-live-extended-thinking"),
            ),
            out_queue=asyncio.Queue(),
            audio_manager=audio,
            status_hub=status,
        )

        connection_task = asyncio.create_task(live.run_connection_loop())
        try:
            deadline = time.monotonic() + 45.0
            while not status.get_status().gemini_connected and time.monotonic() < deadline:
                await asyncio.sleep(0.25)

            if not status.get_status().gemini_connected:
                self.fail(f"Gemini Live did not connect: {status.get_status().last_error}")

            await live.speak_text("LIVE_SMOKE_OK")
            await asyncio.sleep(5.0)
            self.assertTrue(live.get_diagnostics()["connected"])

            generated_chunks = []
            while not audio.audio_in_queue.empty():
                generated_chunks.append(audio.audio_in_queue.get_nowait())
            generated_audio = b"".join(
                chunk if isinstance(chunk, bytes) else bytes(chunk)
                for chunk in generated_chunks
            )
            self.assertTrue(generated_audio, "Gemini Live should return playable speech audio")
        finally:
            await live.stop()
            await asyncio.gather(connection_task, return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
