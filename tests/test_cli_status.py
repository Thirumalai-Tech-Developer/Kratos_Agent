import io
import unittest
from unittest.mock import MagicMock, patch

from rich.console import Console

from kratos_agent import cli
from kratos_agent.core.latency_tracker import latency_tracker


class TestCliStatus(unittest.TestCase):
    def test_status_handles_capability_flags_and_does_not_claim_brain_connected(self):
        live = MagicMock()
        live.get_status.return_value = MagicMock(
            gemini_connected=False,
            live_health="offline",
            muted=True,
            microphone_active=False,
            speaker_active=False,
            screen_active=False,
            camera_active=False,
            last_error="Microphone is muted",
            active_session_id=None,
        )
        supervisor = MagicMock()
        supervisor.get_status.return_value = {
            "status": "idle",
            "active_task_id": None,
            "last_error": None,
        }
        output = io.StringIO()

        with (
            patch("kratos_agent.ccs.get_capability_map", return_value={"os": "Windows", "gui": True, "admin": False}),
            patch("kratos_agent.ccs.get_computer_controller", side_effect=RuntimeError("not initialized")),
            patch("kratos_agent.live.get_live_runtime", return_value=live),
            patch("kratos_agent.master.supervisor.get_master_supervisor", return_value=supervisor),
            patch.object(latency_tracker, "get_last_metrics", return_value=None),
            patch.object(latency_tracker, "get_all_metrics", return_value=[]),
            patch.object(cli, "console", Console(file=output, force_terminal=False)),
        ):
            cli.handle_system_status_command()

        rendered = output.getvalue()
        self.assertIn("1/2 detected feature flags", rendered)
        self.assertIn("CONFIGURED · no chat request verified yet", rendered)
        self.assertNotIn("Brain              │ CONNECTED", rendered)
        self.assertIn("Gemini Live", rendered)
        self.assertIn("Microphone is muted", rendered)


if __name__ == "__main__":
    unittest.main()
