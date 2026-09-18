"""Tests for AgenticMemory, EventStore, and Web API integration with D1."""

import gc
import json
import tempfile
import unittest
import urllib.request
import urllib.parse
from pathlib import Path

from kratos_agent.core.d1_client import D1DatabaseClient
from kratos_agent.core.memory import AgenticMemory
from kratos_agent.core.event_store import EventStore
from kratos_agent.core.runtime_contracts import EventKind, RuntimeEvent
from kratos_agent.web.server import start_server


class TestD1StorageAndWeb(unittest.TestCase):
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

        self.event_store = EventStore(
            session_dir=self.base_path / "sessions" / "test-session-1",
            session_id="test-session-1",
            d1_db=self.d1_db
        )

    def tearDown(self):
        gc.collect()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_memory_session_crud_in_d1(self):
        # 1. Create session
        session = self.memory.create_session(title="Unit Test Session", model="gemini-flash")
        self.assertIsNotNone(session)
        self.assertEqual(session.title, "Unit Test Session")

        # Verify in D1 directly
        res = self.d1_db.execute("SELECT * FROM sessions WHERE id = ?", [session.session_id])
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["title"], "Unit Test Session")

        # 2. Record turn
        turn = self.memory.record_turn(
            user_query="How does D1 work?",
            assistant_response="D1 is serverless SQLite on Cloudflare.",
            tool_calls=[{"name": "fetch_url", "input": {"url": "https://cloudflare.com"}, "result": "ok"}]
        )
        self.assertEqual(turn.get("turn_index"), 0)

        # Verify turn in D1
        turn_res = self.d1_db.execute("SELECT * FROM turns WHERE session_id = ?", [session.session_id])
        self.assertEqual(len(turn_res), 1)
        self.assertEqual(turn_res[0]["user_query"], "How does D1 work?")

        # 3. List sessions
        sessions = self.memory.list_sessions()
        self.assertTrue(any(s["session_id"] == session.session_id for s in sessions))

        # 4. Load session back
        ok = self.memory.load_session(session.session_id)
        self.assertTrue(ok)
        self.assertIsNotNone(self.memory.active_session)
        self.assertEqual(len(self.memory.active_session.turns), 1)
        self.assertEqual(self.memory.active_session.turns[0].get("agent"), "D1 is serverless SQLite on Cloudflare.")

    def test_event_store_records_to_d1(self):
        event = RuntimeEvent(
            kind=EventKind.TOOL_CALL_STARTED,
            turn_id="turn-1",
            payload={"tool": "fetch_url", "url": "https://example.com"}
        )
        self.event_store.append(event)

        # Verify in D1 directly
        res = self.d1_db.execute("SELECT * FROM agentic_events WHERE session_id = ?", ["test-session-1"])
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["kind"], EventKind.TOOL_CALL_STARTED.value)

        # Verify read() from EventStore queries D1
        read_events = self.event_store.read()
        self.assertEqual(len(read_events), 1)
        self.assertEqual(read_events[0]["kind"], EventKind.TOOL_CALL_STARTED.value)

    def test_web_server_endpoints(self):
        # Start server on ephemeral port in background
        server = start_server(port=7890, open_browser=False, d1_db=self.d1_db, memory=self.memory, daemon=True)
        port = server.server_address[1]
        base_url = f"http://127.0.0.1:{port}"

        try:
            # Test /api/stats
            with urllib.request.urlopen(f"{base_url}/api/stats") as response:
                self.assertEqual(response.status, 200)
                data = json.loads(response.read().decode())
                self.assertIn("mode", data)
                self.assertIn("sessions_count", data)

            # Test /api/query
            req = urllib.request.Request(
                f"{base_url}/api/query",
                data=json.dumps({"sql": "SELECT 42 as answer"}).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req) as response:
                self.assertEqual(response.status, 200)
                data = json.loads(response.read().decode())
                self.assertEqual(data["rows"][0]["answer"], 42)
        finally:
            server.shutdown()


if __name__ == "__main__":
    unittest.main()
