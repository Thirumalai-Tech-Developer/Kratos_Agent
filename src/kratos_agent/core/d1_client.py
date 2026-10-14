"""Cloudflare D1 Database Client with local SQLite mirror fallback.

Supports:
- Direct HTTP REST querying against Cloudflare D1 serverless database:
  POST https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{database_id}/query
- Automatic zero-config embedded SQLite mirror when Cloudflare credentials are not configured,
  ensuring 100% offline & local development reliability.
- Schema auto-initialization and migration helpers.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_SCHEMA_PATH = Path(__file__).parent / "d1_schema.sql"
DEFAULT_LOCAL_DB_PATH = Path.cwd() / ".kratos" / "kratos_d1.db"


class D1DatabaseClient:
    """Unified client for Cloudflare D1 with automatic local SQLite fallback."""

    def __init__(
        self,
        account_id: str | None = None,
        database_id: str | None = None,
        api_token: str | None = None,
        local_db_path: Path | None = None,
    ) -> None:
        self.account_id = account_id.strip() if account_id is not None else os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
        self.database_id = database_id.strip() if database_id is not None else os.getenv("CLOUDFLARE_D1_DATABASE_ID", "").strip()
        self.api_token = api_token.strip() if api_token is not None else os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
        self.local_db_path = local_db_path or DEFAULT_LOCAL_DB_PATH
        self.local_db_path.parent.mkdir(parents=True, exist_ok=True)

        self._session = requests.Session()
        self._session.trust_env = False  # Avoid corporate proxy interference
        self._schema_initialized = False
        self._schema_lock = threading.RLock()
        self._remote_lock = threading.RLock()
        self._sync_lock = threading.Lock()
        self._sync_wake = threading.Event()
        self._closed = threading.Event()
        self._sync_thread = None
        self._remote_schema_initialized = False
        self._remote_retry_at = 0.0
        self._remote_schema = []
        # Bind pending writes to the database, never to the secret API token.
        self._remote_target = hashlib.sha256(f'{self.account_id}/{self.database_id}'.encode()).hexdigest()

    @property
    def is_remote(self) -> bool:
        """True if all three Cloudflare credentials are configured in environment."""
        return bool(self.account_id and self.database_id and self.api_token)

    @property
    def endpoint_url(self) -> str:
        """Cloudflare D1 REST query endpoint."""
        return f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/d1/database/{self.database_id}/query"

    def _get_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

    # ── SQL Execution ──────────────────────────────────────────────────────────

    def execute(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        """Persist writes locally and sync them without holding up a model turn."""
        if not self._schema_initialized:
            self.init_schema()
        params = params or []
        from .execution_control import current_cancel_event
        in_turn = current_cancel_event() is not None
        read = sql.lstrip().upper().startswith(('SELECT', 'PRAGMA', 'EXPLAIN'))
        if not read:
            result = self._execute_local(sql, params, enqueue=self.is_remote)
            self._start_sync()
            return result
        # Turn execution and unsynced records use the durable local copy. In
        # particular, Stop must not wait for a cloud query or lose the last turn.
        pending = self._execute_local('SELECT id FROM _kratos_d1_outbox WHERE target = ? LIMIT 1', [self._remote_target])
        self._start_sync()
        if self.is_remote and not in_turn and not pending and time.monotonic() >= self._remote_retry_at:
            try:
                self._init_remote_schema()
                return self._execute_remote(sql, params)
            except Exception:
                self._remote_retry_at = time.monotonic() + 30
        return self._execute_local(sql, params)

    def _init_remote_schema(self):
        with self._remote_lock:
            if self._remote_schema_initialized:
                return
            for statement in self._remote_schema:
                self._execute_remote(statement, [])
            self._remote_schema_initialized = True

    @property
    def has_pending_writes(self):
        if not self._schema_initialized:
            self.init_schema()
        return bool(self._execute_local('SELECT id FROM _kratos_d1_outbox WHERE target = ? LIMIT 1', [self._remote_target]))

    def _start_sync(self):
        if not self.is_remote or self._closed.is_set():
            return
        with self._sync_lock:
            if self._sync_thread is None or not self._sync_thread.is_alive():
                self._sync_thread = threading.Thread(target=self._sync_remote, name='kratos-d1-sync', daemon=True)
                self._sync_thread.start()
            self._sync_wake.set()

    def _sync_remote(self):
        while not self._closed.is_set():
            self._sync_wake.wait(30)
            self._sync_wake.clear()
            if self._closed.is_set():
                return
            remaining = self._remote_retry_at - time.monotonic()
            if remaining > 0 and self._closed.wait(remaining):
                return
            while not self._closed.is_set():
                try:
                    rows = self._execute_local('SELECT * FROM _kratos_d1_outbox WHERE target = ? ORDER BY id LIMIT 1', [self._remote_target])
                    if not rows:
                        break
                    job = rows[0]
                    self._init_remote_schema()
                    # Retrying a lost HTTP acknowledgement must not insert the
                    # same uniquely identified event or turn twice.
                    statement = re.sub(r'^\s*INSERT\s+INTO\b', 'INSERT OR IGNORE INTO', job['sql'], count=1, flags=re.IGNORECASE)
                    self._execute_remote(statement, json.loads(job['params_json']))
                    if self._closed.is_set():
                        return
                    self._execute_local('DELETE FROM _kratos_d1_outbox WHERE id = ?', [job['id']])
                    self._remote_retry_at = 0.0
                except Exception as exc:
                    logger.debug('D1 sync deferred (%s); records remain in the local outbox', type(exc).__name__)
                    self._remote_retry_at = time.monotonic() + 30
                    break

    def close(self):
        """Stop background sync; pending records remain available after restart."""
        self._closed.set()
        self._sync_wake.set()
        if self._sync_thread is not None:
            self._sync_thread.join(timeout=0.5)

    def _execute_remote(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        payload = {
            "sql": sql,
            "params": params,
        }
        with self._remote_lock:
            resp = self._session.post(
                self.endpoint_url,
                headers=self._get_headers(),
                json=payload,
                timeout=5.0,
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

    def _execute_local(self, sql: str, params: list[Any], *, enqueue=False) -> list[dict[str, Any]]:
        conn = sqlite3.connect(self.local_db_path)
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(sql, params)
            if sql.strip().upper().startswith(("SELECT", "PRAGMA")):
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
            if enqueue:
                cursor.execute('INSERT INTO _kratos_d1_outbox (target, sql, params_json) VALUES (?, ?, ?)',
                               [self._remote_target, sql, json.dumps(params)])
            conn.commit()
            return []
        finally:
            conn.close()

    def execute_many(self, sql: str, param_list: list[list[Any]]) -> int:
        """Executes a parameterized statement for multiple rows."""
        count = 0
        for params in param_list:
            self.execute(sql, params)
            count += 1
        return count

    # ── Schema Initialization ──────────────────────────────────────────────────

    def init_schema(self, schema_file: Path | None = None) -> bool:
        with self._schema_lock:
            return self._init_local_schema(schema_file)

    def _init_local_schema(self, schema_file: Path | None = None) -> bool:
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
            cursor.execute('''CREATE TABLE IF NOT EXISTS _kratos_d1_outbox
                              (id INTEGER PRIMARY KEY AUTOINCREMENT, target TEXT NOT NULL,
                               sql TEXT NOT NULL, params_json TEXT NOT NULL)''')
            conn.commit()
        finally:
            conn.close()

        self._remote_schema = statements
        self._schema_initialized = True
        self._start_sync()
        return True

    # ── Statistics & Diagnostic Health ─────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
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
            cog_mem_res = self.execute("SELECT COUNT(*) as c FROM cognitive_memory") or [{}]
            cognitive_memory_count = cog_mem_res[0].get("c", 0) if cog_mem_res else 0
            is_healthy = True
        except Exception as exc:
            sessions_count = turns_count = events_count = commands_count = cognitive_memory_count = 0
            error_msg = str(exc)

        latency_ms = (time.monotonic() - start) * 1000

        return {
            "mode": mode,
            "pending_sync": len(self._execute_local('SELECT id FROM _kratos_d1_outbox WHERE target = ?', [self._remote_target])),
            "is_remote": self.is_remote,
            "is_healthy": is_healthy,
            "database_id": self.database_id or "(local mirror)",
            "account_id": self.account_id[:6] + "..." if len(self.account_id) > 6 else "(none)",
            "latency_ms": round(latency_ms, 1),
            "sessions_count": sessions_count,
            "turns_count": turns_count,
            "events_count": events_count,
            "commands_count": commands_count,
            "cognitive_memory_count": cognitive_memory_count,
            "error": error_msg,
        }

    def optimize(self) -> dict[str, Any]:
        """Runs PRAGMA wal_checkpoint(TRUNCATE), PRAGMA optimize, and VACUUM to reclaim space and defragment."""
        reclaimed_bytes = 0
        initial_size = 0
        final_size = 0
        wal_path = self.local_db_path.with_name(self.local_db_path.name + "-wal")
        if self.local_db_path.exists():
            try:
                initial_size = self.local_db_path.stat().st_size
                if wal_path.exists():
                    initial_size += wal_path.stat().st_size

                conn = sqlite3.connect(str(self.local_db_path))
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.execute("PRAGMA optimize")
                conn.execute("VACUUM")
                conn.close()

                final_size = self.local_db_path.stat().st_size
                if wal_path.exists():
                    final_size += wal_path.stat().st_size

                reclaimed_bytes = max(0, initial_size - final_size)
            except Exception as exc:
                logger.debug("Database optimize error: %s", exc)
        return {
            "initial_size_bytes": initial_size,
            "final_size_bytes": final_size,
            "reclaimed_bytes": reclaimed_bytes,
        }


# Global D1 database singleton client
d1_db = D1DatabaseClient()


def get_d1_client() -> D1DatabaseClient:
    """Returns the global singleton D1DatabaseClient instance."""
    return d1_db
