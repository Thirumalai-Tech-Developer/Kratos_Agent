"""Tests for Kratos Vice Web Server live chat, tools discovery, and telemetry."""

import json
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock

from kratos_agent.core.d1_client import D1DatabaseClient
from kratos_agent.core.memory import AgenticMemory
from kratos_agent.web.server import start_server


class TestWebLiveChatAndTelemetry(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        self.db_path = self.base_path / "test_d1.db"
        self.d1_db = D1DatabaseClient(local_db_path=self.db_path)
        self.d1_db.init_schema()

        self.memory = AgenticMemory(
            sessions_dir=self.base_path / "sessions",
            d1_db=self.d1_db
        )

        # Mock runtime
        self.mock_runtime = MagicMock()
        self.mock_runtime.model_name = "antigravity/gemini-3.7-flash-high"
        self.mock_runtime.workspace = self.base_path
        self.mock_runtime.memory = self.memory
        mock_tool = MagicMock()
        mock_tool.name = "read_file"
        mock_tool.description = "Read a file from disk"
        mock_tool.permission = MagicMock(value="read")
        self.mock_runtime.tools = [mock_tool]
        self.mock_runtime.run_agent.return_value = "Hello recruiter! Kratos Agent is online."

        # Start web server
        self.server = start_server(
            port=7910,
            open_browser=False,
            d1_db=self.d1_db,
            memory=self.memory,
            runtime=self.mock_runtime,
            daemon=True
        )
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"

    def tearDown(self):
        self.server.shutdown()
        import gc
        gc.collect()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_get_tools_endpoint(self):
        with urllib.request.urlopen(f"{self.base_url}/api/tools") as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode())
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["name"], "read_file")

    def test_get_telemetry_endpoint(self):
        with urllib.request.urlopen(f"{self.base_url}/api/telemetry") as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode())
            self.assertEqual(data["model"], "antigravity/gemini-3.7-flash-high")
            self.assertEqual(data["tools_count"], 1)

    def test_chat_sync_endpoint(self):
        req = urllib.request.Request(
            f"{self.base_url}/api/chat/sync",
            data=json.dumps({"prompt": "Hello"}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode())
            self.assertEqual(data["result"], "Hello recruiter! Kratos Agent is online.")

    def test_chat_sse_stream_endpoint(self):
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps({"prompt": "Test prompt"}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/event-stream", resp.headers.get("Content-Type", ""))
            chunks = []
            for _ in range(20):
                line = resp.readline().decode("utf-8")
                if not line:
                    break
                chunks.append(line)
                if '"type": "done"' in line:
                    break
            joined = "".join(chunks)
            self.assertIn("data: ", joined)
            self.assertIn('"type": "start"', joined)


if __name__ == "__main__":
    unittest.main()
