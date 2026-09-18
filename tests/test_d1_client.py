"""Tests for D1DatabaseClient (Local mirror & query execution)."""

import os
import tempfile
import unittest
from pathlib import Path

from kratos_agent.core.d1_client import D1DatabaseClient


class TestD1DatabaseClient(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_d1.db"
        self.client = D1DatabaseClient(
            account_id="",
            database_id="",
            api_token="",
            local_db_path=self.db_path
        )
        self.client.init_schema()

    def tearDown(self):
        import gc
        gc.collect()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_init_schema_creates_tables(self):
        # Query sqlite_master to verify tables
        rows = self.client.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        table_names = [r["name"] for r in rows]
        self.assertIn("sessions", table_names)
        self.assertIn("turns", table_names)
        self.assertIn("agentic_events", table_names)
        self.assertIn("commands", table_names)

    def test_execute_insert_and_select(self):
        # Insert a session
        self.client.execute(
            "INSERT INTO sessions (id, title, model, created_at, updated_at, last_status) VALUES (?, ?, ?, ?, ?, ?)",
            ["sess-100", "Test Session", "test-model", "2026-09-05T12:00:00Z", "2026-09-05T12:00:00Z", "active"]
        )

        # Select it back
        rows = self.client.execute("SELECT * FROM sessions WHERE id = ?", ["sess-100"])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["id"], "sess-100")
        self.assertEqual(row["title"], "Test Session")
        self.assertEqual(row["model"], "test-model")

    def test_execute_many(self):
        param_list = [
            ["s1", "Session 1", "2026-09-05", "2026-09-05"],
            ["s2", "Session 2", "2026-09-05", "2026-09-05"],
        ]
        sql = "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)"
        count = self.client.execute_many(sql, param_list)
        self.assertEqual(count, 2)

        count_rows = self.client.execute("SELECT COUNT(*) as cnt FROM sessions")
        self.assertEqual(count_rows[0]["cnt"], 2)

    def test_get_stats(self):
        self.client.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ["s1", "Session 1", "2026-09-05", "2026-09-05"]
        )
        self.client.execute(
            "INSERT INTO agentic_events (id, session_id, kind, timestamp, payload_json) VALUES (?, ?, ?, ?, ?)",
            ["ev-1", "s1", "tool_call", 1725537600.0, '{"info": "Calling tool"}']
        )
        stats = self.client.get_stats()
        self.assertEqual(stats["sessions_count"], 1)
        self.assertEqual(stats["events_count"], 1)
        self.assertEqual(stats["mode"], "local_sqlite")


if __name__ == "__main__":
    unittest.main()
