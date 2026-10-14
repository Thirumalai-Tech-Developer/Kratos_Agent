"""Durable, pre-compaction execution capture and reproducible dataset export."""
from __future__ import annotations

import hashlib
import gzip
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid
from typing import Any

_SECRET_KEY = re.compile(r"(?:api[_-]?key|authorization|password|passwd|secret|access[_-]?token|refresh[_-]?token|id[_-]?token|cookie|code[_-]?verifier)", re.I)
_sensitive_values: set[str] = set()
_sensitive_lock = threading.RLock()


def register_sensitive_values(*values: str) -> None:
    """Remember runtime-only OAuth secrets so incidental tool output is scrubbed."""
    with _sensitive_lock:
        _sensitive_values.update(v for v in values if isinstance(v, str) and len(v) >= 8)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): "[REDACTED]" if _SECRET_KEY.search(str(k)) else redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        with _sensitive_lock:
            for secret in _sensitive_values:
                value = value.replace(secret, "[REDACTED]")
        for name, secret in os.environ.items():
            if _SECRET_KEY.search(name) and len(secret) >= 8:
                value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"(?i)\bBearer\s+[\w./+\-=]+", "Bearer [REDACTED]", value)
        value = re.sub(r"(?im)\b([\w]*(?:API_KEY|PASSWORD|SECRET|ACCESS_TOKEN|REFRESH_TOKEN|ID_TOKEN|COOKIE|CODE_VERIFIER)[\w]*)\s*[:=]\s*[^\r\n]+", r"\1=[REDACTED]", value)
        return re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----", "[REDACTED PRIVATE KEY]", value)
    if hasattr(value, "to_dict"):
        return redact(value.to_dict())
    return value


class ExecutionArchive:
    """SQLite is authoritative; JSONL is a replayable mirror, not an expiring cache."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir(exist_ok=True)
        self.path = self.root / "records.db"
        self._lock = threading.RLock()
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS records (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE, session_id TEXT,
                    run_id TEXT, kind TEXT, created REAL, payload TEXT, checksum TEXT);
                CREATE INDEX IF NOT EXISTS records_run ON records(session_id,run_id,seq);
            """)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.row_factory = sqlite3.Row
            with db:
                yield db
        finally:
            db.close()

    def record(self, kind: str, payload: Any, session_id: str = "", run_id: str = "") -> str:
        body = json.dumps(redact(payload), ensure_ascii=False, default=str)
        item = {"id": uuid.uuid4().hex, "session_id": session_id, "run_id": run_id,
                "kind": kind, "created": time.time(), "payload": json.loads(body),
                "checksum": hashlib.sha256(body.encode()).hexdigest()}
        with self._lock, self._connect() as db:
            cursor = db.execute("INSERT INTO records(id,session_id,run_id,kind,created,payload,checksum) VALUES(?,?,?,?,?,?,?)",
                       (item["id"], session_id, run_id, kind, item["created"], body, item["checksum"]))
            item["seq"] = cursor.lastrowid
        # The database commit above is the capture boundary. Mirror failure is visible.
        mirror = self.root / f"events-{time.strftime('%Y%m%d')}.jsonl"
        with self._lock, mirror.open("a", encoding="utf-8") as output:
            output.write(json.dumps(item, ensure_ascii=False) + "\n")
        return item["id"]

    def compress_mirrors(self):
        """Compress closed daily mirrors; the indexed database remains authoritative."""
        today = f"events-{time.strftime('%Y%m%d')}.jsonl"
        count = 0
        with self._lock:
            for path in self.root.glob("events-*.jsonl"):
                if path.name == today:
                    continue
                target = path.with_suffix(".jsonl.gz")
                temporary = target.with_suffix(".tmp")
                with path.open("rb") as source, gzip.open(temporary, "wb") as output:
                    import shutil
                    shutil.copyfileobj(source, output)
                temporary.replace(target)
                path.unlink()
                count += 1
        return {"compressed": count}

    def artifact(self, content: bytes, suffix: str = ".bin") -> dict[str, Any]:
        digest = hashlib.sha256(content).hexdigest()
        safe_suffix = suffix if re.fullmatch(r"\.[a-zA-Z0-9]{1,10}", suffix) else ".bin"
        target = self.artifacts / (digest + safe_suffix)
        with self._lock:
            if not target.exists():
                target.write_bytes(content)
        return {"sha256": digest, "path": str(target), "bytes": len(content)}

    def capture_file(self, path: Path):
        path = Path(path)
        if not path.is_file():
            return None
        from kratos_agent.brain.account_store import account_directory
        if path.resolve().is_relative_to(account_directory().resolve()) or path.name == "accounts.bin":
            return {"excluded": "credential_file", "path": str(path)}
        if path.name.startswith(".env") or path.name.lower() in {"api_token", "credentials", "credentials.json"} or path.suffix.lower() in {".pem", ".key", ".p12"}:
            return {"excluded": "credential_file", "path": str(path)}
        data = path.read_bytes()
        binary = path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".wav", ".mp3", ".mp4", ".pdf", ".docx", ".xlsx", ".pptx", ".zip"}
        return self.artifact(data if binary else redact(data.decode("utf-8", errors="replace")).encode(), path.suffix if binary else ".txt")

    def records(self, session_id: str | None = None, limit: int | None = None, after_seq: int = 0):
        with self._connect() as db:
            query, params = "SELECT * FROM records WHERE seq>?", [after_seq]
            if session_id:
                query += " AND session_id=?"
                params.append(session_id)
            query += " ORDER BY seq"
            if limit is not None:
                query += " LIMIT ?"
                params.append(limit)
            return [{**dict(row), "payload": json.loads(row["payload"])} for row in db.execute(query, params)]

    def stats(self):
        with self._connect() as db:
            count = db.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        return {"records": count, "bytes": sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file()),
                "path": str(self.root)}

    def export(self, destination: Path, *, format: str = "jsonl") -> dict[str, Any]:
        """Export labeled trajectories. Verified labels require recorded evidence."""
        groups: dict[tuple[str, str], list[dict]] = {}
        for item in self.records():
            groups.setdefault((item["session_id"], item["run_id"]), []).append(item)
        examples, seen = [], set()
        for (session, run), items in groups.items():
            starts = [r for r in items if r["kind"] == "run.input"]
            finals = [r for r in items if r["kind"] == "run.output"]
            if not starts or not finals:
                continue
            first, last = starts[-1]["payload"], finals[-1]["payload"]
            canonical = [first.get("prompt"), first.get("model"), first.get("behavior", {}).get("version"),
                         last.get("response"), last.get("status"), last.get("verification")]
            fingerprint = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            split_key = first.get("workspace", session)
            bucket = int(hashlib.sha256(str(split_key).encode()).hexdigest()[:8], 16) % 10
            examples.append({"schema_version": 1, "id": fingerprint, "session_id": session, "run_id": run,
                             "split": "test" if bucket == 0 else "validation" if bucket == 1 else "train",
                             "messages": self.training_messages(first, last, items),
                             "status": last.get("status", "unverified"),
                             "verified": last.get("status") == "completed" and bool(last.get("verification", {}).get("passed", False)),
                             "quality_label": "verified_success" if last.get("status") == "completed" and last.get("verification", {}).get("passed") else last.get("status", "unverified"),
                             "checkpoints": [r["payload"] for r in items if r["kind"] == "context.compacted"],
                             "trajectory": items})
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if format == "parquet":
            import pyarrow as pa
            import pyarrow.parquet as pq
            rows = [{**e, "messages": json.dumps(e["messages"]), "trajectory": json.dumps(e["trajectory"]), "checkpoints": json.dumps(e["checkpoints"])} for e in examples]
            table = pa.Table.from_pylist(rows) if rows else pa.table({"id": pa.array([], type=pa.string())})
            pq.write_table(table, destination)
        else:
            with destination.open("w", encoding="utf-8") as output:
                for item in examples:
                    output.write(json.dumps(item, ensure_ascii=False) + "\n")
        return {"examples": len(examples), "path": str(destination), "format": format}

    @staticmethod
    def training_messages(first, last, records):
        """Preserve native tool-call IDs for supervised tool-use distillation."""
        messages = [{"role": "user", "content": first.get("prompt", "")}]
        # SDK captures have the full returned text and actual call arguments.
        for record in records:
            payload = record["payload"]
            if record["kind"] == "model.response":
                item = {"role": "assistant", "content": payload.get("text", "")}
                calls = payload.get("tool_calls", [])
                if calls:
                    item["tool_calls"] = [{"id": call.get("id", call.get("call_id", "")), "type": "function",
                                            "function": {"name": call["name"], "arguments": json.dumps(call.get("arguments", {}))}} for call in calls]
                # Runtime event mirrors nest the payload and are already present in trajectory.
                if item["content"] or calls:
                    messages.append(item)
            elif record["kind"] == "tool.result" and payload.get("name") and payload.get("call_id"):
                messages.append({"role": "tool", "name": payload["name"], "tool_call_id": payload["call_id"], "content": payload.get("content", "")})
        if len(messages) == 1 or messages[-1].get("content") != last.get("response", ""):
            messages.append({"role": "assistant", "content": last.get("response", "")})
        return messages
