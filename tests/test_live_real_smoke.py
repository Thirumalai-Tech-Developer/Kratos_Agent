"""Opt-in real Gemini Live smoke test.

Run on a real Kratos host with Python 3.14+ and Gemini credentials:
    KRATOS_RUN_LIVE_TESTS=1 pytest -q tests/test_live_real_smoke.py -s

The smoke test uses a harmless `observe` tool backed by synthetic dimensions, so it
verifies the real Gemini Live connection, function-call round trip, async tool
response, and Extended Thinking interaction lifecycle without changing the desktop.
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
    async def test_real_gemini_live_observe_roundtrip(self):
        from kratos_agent.live.config import LiveConfig
        from kratos_agent.live.events import LiveStatusHub
        from kratos_agent.live.router import LiveRouter
        from kratos_agent.live.session import LiveSession

        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            self.skipTest("Gemini API key is not configured")

        status = LiveStatusHub()
        router = LiveRouter(
            bridge=SimpleNamespace(get_status=lambda task_id=None: {"status": "idle"}),
            capture_screen_handler=lambda: SimpleNamespace(width=1920, height=1080),
        )
        audio = SimpleNamespace(audio_in_queue=asyncio.Queue())
        live = LiveSession(
            config=LiveConfig(
                api_key=api_key,
                enabled=True,
                model=os.getenv("KRATOS_LIVE_MODEL", "gemini-3.8-live-extended-thinking"),
            ),
            out_queue=asyncio.Queue(),
            audio_manager=audio,
            router=router,
            status_hub=status,
        )

        connection_task = asyncio.create_task(live.run_connection_loop())
        try:
            deadline = time.monotonic() + 45.0
            while not status.get_status().gemini_connected and time.monotonic() < deadline:
                await asyncio.sleep(0.25)

            if not status.get_status().gemini_connected:
                self.fail(f"Gemini Live did not connect: {status.get_status().last_error}")

            reply = await live.send_text_turn(
                "Run the observe tool once, then reply with the exact token LIVE_SMOKE_OK.",
                timeout=35.0,
            )
            self.assertIn("LIVE_SMOKE_OK", reply)
            self.assertTrue(live.get_diagnostics()["connected"])
        finally:
            await live.stop()
            await asyncio.gather(connection_task, return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
