"""Local HTTP integration checks for Live status and vision-mode controls."""
import json
import threading
import time
import unittest
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from kratos_agent.live.config import LiveConfig
from kratos_agent.live.runtime import LiveRuntime
from kratos_agent.web.server import KratosServer, KratosWebHandler


class LiveControlEndpointTests(unittest.TestCase):
    def test_offline_runtime_reports_status_and_accepts_vision_off(self):
        runtime = LiveRuntime(config=LiveConfig(api_key="", enabled=True))
        server = KratosServer(
            ("127.0.0.1", 0),
            KratosWebHandler,
            d1_db=SimpleNamespace(is_remote=False),
            memory=object(),
            runtime=object(),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        hearing = SimpleNamespace(start=lambda: None, stop=lambda: None, mute=lambda: None, unmute=lambda: None)
        with patch("kratos_agent.live.native_listener.get_native_hearing", return_value=hearing):
            runtime.start_in_background()
            deadline = time.monotonic() + 5
            while not hasattr(runtime, "native_hearing"):
                if time.monotonic() > deadline:
                    self.fail("Local speech-listener setup did not finish")
                time.sleep(0.01)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"

        try:
            deadline = time.monotonic() + 5
            while not (runtime._loop and runtime._loop.is_running()):
                if time.monotonic() > deadline:
                    self.fail("Live control loop did not start")
                time.sleep(0.01)

            with patch("kratos_agent.live.get_live_runtime", return_value=runtime):
                with urlopen(f"{base_url}/api/live/status", timeout=3) as response:
                    status = json.loads(response.read())
                self.assertFalse(status["gemini_connected"])
                self.assertFalse(status["speaker_active"])

                request = Request(
                    f"{base_url}/api/live/control",
                    data=json.dumps({"action": "set_vision_mode", "value": "none"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=3) as response:
                    updated = json.loads(response.read())
                self.assertEqual(updated["video_mode"], "none")
                self.assertFalse(updated["camera_active"])
                self.assertFalse(updated["screen_active"])

                avatar_request = Request(
                    f"{base_url}/api/live/control",
                    data=json.dumps({"action": "avatar_toggle"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(HTTPError) as error:
                    urlopen(avatar_request, timeout=3)
                self.assertEqual(error.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            runtime.stop_background()


if __name__ == "__main__":
    unittest.main()
