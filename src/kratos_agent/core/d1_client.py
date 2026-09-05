"""Cloudflare D1 Database Client with local SQLite mirror fallback.

Supports:
- Direct HTTP REST querying against Cloudflare D1 serverless database:
  POST https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{database_id}/query
- Automatic zero-config embedded SQLite mirror when Cloudflare credentials are not configured,
  ensuring 100% offline & local development reliability.
- Schema auto-initialization and migration helpers.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_SCHEMA_PATH = Path(__file__).parent / "d1_schema.sql"
DEFAULT_LOCAL_DB_PATH = Path.cwd() / ".kratos" / "kratos_d1.db"


class D1DatabaseClient:
    """Unified client for Cloudflare D1 with automatic local SQLite fallback."""

    def __init__(
        self,
        account_id: Optional[str] = None,
        database_id: Optional[str] = None,
        api_token: Optional[str] = None,
        local_db_path: Optional[Path] = None,
    ) -> None:
        self.account_id = account_id or os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
        self.database_id = database_id or os.getenv("CLOUDFLARE_D1_DATABASE_ID", "").strip()
        self.api_token = api_token or os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
        self.local_db_path = local_db_path or DEFAULT_LOCAL_DB_PATH
        self.local_db_path.parent.mkdir(parents=True, exist_ok=True)

        self._session = requests.Session()
        self._session.trust_env = False  # Avoid corporate proxy interference
        self._schema_initialized = False

    @property
    def is_remote(self) -> bool:
        """True if all three Cloudflare credentials are configured in environment."""
        return bool(self.account_id and self.database_id and self.api_token)

    @property
    def endpoint_url(self) -> str:
        """Cloudflare D1 REST query endpoint."""
        return f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/d1/database/{self.database_id}/query"

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

    # ── SQL Execution ──────────────────────────────────────────────────────────

    def execute(self, sql: str, params: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
        """Executes a SQL query and returns rows as dictionaries."""
        if not self._schema_initialized:
            self.init_schema()

        if self.is_remote:
            try:
                return self._execute_remote(sql, params or [])
            except Exception as exc:
                # Log and fallback gracefully to local mirror on network or remote error
                return self._execute_local(sql, params or [])
        else:
            return self._execute_local(sql, params or [])

    def _execute_remote(self, sql: str, params: List[Any]) -> List[Dict[str, Any]]:
        payload = {
            "sql": sql,
            "params": params,
        }
        resp = self._session.post(
            self.endpoint_url,
            headers=self._get_headers(),
            json=payload,
            timeout=15.0,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Cloudflare D1 HTTP {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        if not data.get("success", False):
            errors = data.get("errors", [])
            err_msg = "; ".join(e.get("message", str(e)) for e in errors) or "Unknown D1 Error"
            raise RuntimeError(f"Cloudflare D1 query error: {err_msg}")

        result_blocks = data.get("result", [])
        if not result_blocks:
            return []

        # Return results of the primary statement block
        return result_blocks[0].get("results", [])

    def _execute_local(self, sql: str, params: List[Any]) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.local_db_path)
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(sql, params)
            if sql.strip().upper().startswith(("SELECT", "PRAGMA")):
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
            conn.commit()
            return []
        finally:
            conn.close()

    def execute_many(self, sql: str, param_list: List[List[Any]]) -> int:
        """Executes a parameterized statement for multiple rows."""
        count = 0
        for params in param_list:
            self.execute(sql, params)
            count += 1
        return count

    # ── Schema Initialization ──────────────────────────────────────────────────

    def init_schema(self, schema_file: Optional[Path] = None) -> bool:
        """Initializes tables and indices from d1_schema.sql."""
        path = schema_file or DEFAULT_SCHEMA_PATH
        if not path.exists():
            return False

        sql_content = path.read_text(encoding="utf-8")
        statements = [s.strip() for s in sql_content.split(";") if s.strip()]

        # Always initialize local SQLite schema
        conn = sqlite3.connect(self.local_db_path)
        try:
            cursor = conn.cursor()
            for stmt in statements:
                cursor.execute(stmt)
            conn.commit()
        finally:
            conn.close()

        # If Cloudflare D1 credentials are set, also initialize remote D1 tables
        if self.is_remote:
            try:
                for stmt in statements:
                    self._execute_remote(stmt, [])
            except Exception:
                pass

        self._schema_initialized = True
        return True

    # ── Statistics & Diagnostic Health ─────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Returns database statistics, connection mode, and record counts."""
        start = time.monotonic()
        mode = "cloudflare_d1" if self.is_remote else "local_sqlite"
        is_healthy = False
        error_msg = ""

        try:
            sessions_count = (self.execute("SELECT COUNT(*) as c FROM sessions") or [{}])[0].get("c", 0)
            turns_count = (self.execute("SELECT COUNT(*) as c FROM turns") or [{}])[0].get("c", 0)
            events_count = (self.execute("SELECT COUNT(*) as c FROM agentic_events") or [{}])[0].get("c", 0)
            commands_count = (self.execute("SELECT COUNT(*) as c FROM commands") or [{}])[0].get("c", 0)
            is_healthy = True
        except Exception as exc:
            sessions_count = turns_count = events_count = commands_count = 0
            error_msg = str(exc)

        latency_ms = (time.monotonic() - start) * 1000

        return {
            "mode": mode,
            "is_remote": self.is_remote,
            "is_healthy": is_healthy,
            "database_id": self.database_id or "(local mirror)",
            "account_id": self.account_id[:6] + "..." if len(self.account_id) > 6 else "(none)",
            "latency_ms": round(latency_ms, 1),
            "sessions_count": sessions_count,
            "turns_count": turns_count,
            "events_count": events_count,
            "commands_count": commands_count,
            "error": error_msg,
        }


# Global D1 database singleton client
d1_db = D1DatabaseClient()


def get_d1_client() -> D1DatabaseClient:
    """Returns the global singleton D1DatabaseClient instance."""
    return d1_db
