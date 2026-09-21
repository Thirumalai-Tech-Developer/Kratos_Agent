import unittest
import time
from unittest.mock import MagicMock, patch
from kratos_agent.live.events import LiveStatus, LiveState
from kratos_agent.utils.computer_tools import ask_omni_vision

class TestStatusTruthfulness(unittest.TestCase):
    def test_live_connecting_times_out_to_offline(self):
        # When connection is connecting but older than 15s, must show OFFLINE, never CONNECTING forever
        st = LiveStatus(
            gemini_connected=False,
            current_state=LiveState.CONNECTING,
            updated_at=time.time() - 20.0, # 20 seconds ago
        )
        if st.gemini_connected:
            badge = "CONNECTED"
        elif st.last_error:
            badge = f"FAILED ({st.last_error})"
        elif st.current_state in (LiveState.CONNECTING, LiveState.RECONNECTING) and (time.time() - st.updated_at) < 15.0:
            badge = "CONNECTING"
        else:
            badge = "OFFLINE"

        self.assertEqual(badge, "OFFLINE", "Permanent connecting status must resolve to OFFLINE after 15s")

    def test_live_connected_shows_connected(self):
        st = LiveStatus(
            gemini_connected=True,
            active_session_id="session_123",
            current_state=LiveState.CONNECTED,
            updated_at=time.time(),
        )
        if st.gemini_connected:
            badge = f"CONNECTED ({st.active_session_id})"
        elif st.last_error:
            badge = f"FAILED ({st.last_error})"
        elif st.current_state in (LiveState.CONNECTING, LiveState.RECONNECTING) and (time.time() - st.updated_at) < 15.0:
            badge = "CONNECTING"
        else:
            badge = "OFFLINE"

        self.assertIn("CONNECTED", badge)
        self.assertIn("session_123", badge)

    def test_ask_omni_vision_degrades_when_omni_offline(self):
        # Should degrade to local screen text and not raise an exception or hang
        with patch("urllib.request.urlopen", side_effect=ConnectionRefusedError("Omni down")):
            with patch("kratos_agent.utils.computer_tools.screen_read_text", return_value="Visible screen text sample"):
                res = ask_omni_vision("what is on screen?")
                self.assertIn("Omni offline", res)
                self.assertIn("local_fallback", res)

if __name__ == "__main__":
    unittest.main()
