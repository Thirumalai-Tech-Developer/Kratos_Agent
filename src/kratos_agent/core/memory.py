from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .d1_client import D1DatabaseClient, d1_db

KRATOS_DIR = Path.cwd() / ".kratos"
SESSIONS_DIR = KRATOS_DIR / "sessions"
LEGACY_MEMORY_FILE = KRATOS_DIR / "agent_memory.json"
INDEX_FILE = SESSIONS_DIR / "index.json"


class AgenticSession:
    def __init__(self, session_id: str, title: str = "New Session", model: str = "gemini-3.6-flash-high", created_at: Optional[str] = None):
        self.session_id = session_id
        self.title = title
        self.model = model
        self.created_at = created_at or time.strftime("%Y-%m-%d %H:%M:%S")
        self.updated_at = self.created_at
        self.turns: List[Dict[str, Any]] = []
        self.executed_commands: List[Dict[str, Any]] = []
        self.created_artifacts: List[Dict[str, Any]] = []
        self.notes: Dict[str, Any] = {}
        self.plan: Optional[Dict[str, Any]] = None
        self.files_changed: Dict[str, List[str]] = {"created": [], "modified": [], "deleted": []}
        self.last_status: str = "idle"
        self.verification_status: Dict[str, Any] = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "model": self.model,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "turns": self.turns,
            "executed_commands": self.executed_commands,
            "created_artifacts": self.created_artifacts,
            "notes": self.notes,
            "plan": self.plan,
            "files_changed": self.files_changed,
            "last_status": self.last_status,
            "verification_status": self.verification_status,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AgenticSession:
        session = cls(
            session_id=data.get("session_id", str(uuid.uuid4())[:8]),
            title=data.get("title", "Untitled Session"),
            model=data.get("model", "gemini-3.6-flash-high"),
            created_at=data.get("created_at")
        )
        session.updated_at = data.get("updated_at", session.created_at)
        session.turns = data.get("turns", [])
        session.executed_commands = data.get("executed_commands", [])
        session.created_artifacts = data.get("created_artifacts", [])
        session.notes = data.get("notes", {})
        session.plan = data.get("plan")
        session.files_changed = data.get("files_changed", {"created": [], "modified": [], "deleted": []})
        session.last_status = data.get("last_status", "idle")
        session.verification_status = data.get("verification_status", {})
        return session

    def set_plan(self, plan_dict_or_obj: Any) -> None:
        if hasattr(plan_dict_or_obj, "to_dict"):
            self.plan = plan_dict_or_obj.to_dict()
        elif isinstance(plan_dict_or_obj, dict):
            self.plan = plan_dict_or_obj
        else:
            self.plan = None

    def get_plan(self) -> Optional[Any]:
        if not self.plan:
            return None
        from kratos_agent.core.task_manager import ExecutionPlan
        return ExecutionPlan.from_dict(self.plan)

    def has_unfinished_plan(self) -> bool:
        plan = self.get_plan()
        if not plan or not plan.tasks:
            return False
        return any(t.state in ("pending", "running", "needs_attention", "failed") for t in plan.tasks)

    def get_unfinished_tasks_summary(self) -> str:
        plan = self.get_plan()
        if not plan:
            return "No active plan."
        completed = len([t for t in plan.tasks if t.state == "completed"])
        interrupted = len([t for t in plan.tasks if t.state in ("running", "needs_attention")])
        pending = len([t for t in plan.tasks if t.state == "pending"])
        failed = len([t for t in plan.tasks if t.state == "failed"])
        return f"✓ {completed} completed  ⠋ {interrupted} interrupted  ☐ {pending} pending" + (f"  ✗ {failed} failed" if failed else "")


class AgenticMemory:
    """Manages multi-session persistent agent memory, command logs, and context isolation via Cloudflare D1."""

    def __init__(
        self,
        sessions_dir: Optional[Path] = None,
        db: Optional[D1DatabaseClient] = None,
        d1_db: Optional[D1DatabaseClient] = None,
        **kwargs: Any,
    ):
        self.sessions_dir = sessions_dir or SESSIONS_DIR
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.sessions_dir / "index.json"
        self.db = d1_db or db
        if self.db is None:
            from .d1_client import d1_db as default_d1
            self.db = default_d1
        try:
            self.db.init_schema()
        except Exception:
            pass

        self.active_session: Optional[AgenticSession] = None
        self._init_or_load_latest()

    def _init_or_load_latest(self):
        """Loads the most recent active session from Cloudflare D1 or initializes a new session."""
        index = self._load_index()
        if index.get("active_session_id"):
            loaded = self.load_session(index["active_session_id"])
            if loaded:
                return

        # Check if any sessions exist in D1 DB or on disk
        sessions = self.list_sessions()
        if sessions:
            self.load_session(sessions[0]["session_id"])
            return

        # Check for legacy memory migration
        if LEGACY_MEMORY_FILE.exists():
            try:
                legacy_data = json.loads(LEGACY_MEMORY_FILE.read_text(encoding="utf-8"))
                legacy_turns = legacy_data.get("sessions", [])
                legacy_cmds = legacy_data.get("executed_commands", [])
                if legacy_turns or legacy_cmds:
                    session = self.create_session(title="Migrated History")
                    session.turns = legacy_turns
                    session.executed_commands = legacy_cmds
                    self.save()
                    return
            except Exception:
                pass

        # Create initial session
        self.create_session("Default Session")

    def _load_index(self) -> Dict[str, Any]:
        if self.index_file.exists():
            try:
                return json.loads(self.index_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"sessions": [], "active_session_id": None}

    def _save_index(self, index: Dict[str, Any]):
        try:
            self.index_file.write_text(json.dumps(index, indent=2), encoding="utf-8")
        except Exception:
            pass

    def create_session(self, title: Optional[str] = None, model: str = "gemini-3.6-flash-high") -> AgenticSession:
        """Creates, persists to Cloudflare D1, and activates a new session."""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        short_id = uuid.uuid4().hex[:6]
        session_id = f"session_{timestamp}_{short_id}"
        session_title = title or f"Session {time.strftime('%b %d, %H:%M')}"

        session = AgenticSession(session_id=session_id, title=session_title, model=model)
        self.active_session = session

        # Persist session to Cloudflare D1 database
        try:
            self.db.execute(
                """INSERT OR REPLACE INTO sessions 
                   (id, title, model, created_at, updated_at, last_status, plan_json, files_changed_json, verification_status_json, notes_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    session.session_id,
                    session.title,
                    session.model,
                    session.created_at,
                    session.updated_at,
                    session.last_status,
                    json.dumps(session.plan or {}),
                    json.dumps(session.files_changed or {}),
                    json.dumps(session.verification_status or {}),
                    json.dumps(session.notes or {}),
                ],
            )
        except Exception:
            pass

        # Save session file for local backup
        self._save_file_backup()

        # Update index
        index = self._load_index()
        index["active_session_id"] = session_id
        session_entry = {
            "session_id": session_id,
            "title": session_title,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "turns_count": 0,
            "model": model,
        }
        index["sessions"] = [s for s in index.get("sessions", []) if s.get("session_id") != session_id]
        index["sessions"].insert(0, session_entry)
        self._save_index(index)

        return session

    def load_session(self, session_id: str) -> bool:
        """Loads a session from Cloudflare D1 database, falling back to disk backup."""
        # 1. Try loading from D1 DB
        try:
            rows = self.db.execute("SELECT * FROM sessions WHERE id = ?", [session_id])
            if rows:
                row = rows[0]
                session = AgenticSession(
                    session_id=row.get("id", session_id),
                    title=row.get("title", "Session"),
                    model=row.get("model", "gemini-3.6-flash-high"),
                    created_at=row.get("created_at"),
                )
                session.updated_at = row.get("updated_at", session.created_at)
                session.last_status = row.get("last_status", "idle")

                try:
                    session.plan = json.loads(row.get("plan_json") or "{}") if row.get("plan_json") else None
                except Exception:
                    session.plan = None

                try:
                    session.files_changed = json.loads(row.get("files_changed_json") or "{}") if row.get("files_changed_json") else {}
                except Exception:
                    session.files_changed = {}

                try:
                    session.verification_status = json.loads(row.get("verification_status_json") or "{}") if row.get("verification_status_json") else {}
                except Exception:
                    session.verification_status = {}

                try:
                    session.notes = json.loads(row.get("notes_json") or "{}") if row.get("notes_json") else {}
                except Exception:
                    session.notes = {}

                # Load turns from D1 turns table
                turn_rows = self.db.execute("SELECT * FROM turns WHERE session_id = ? ORDER BY turn_index ASC", [session_id])
                for tr in turn_rows:
                    tools = []
                    if tr.get("tools_used_json"):
                        try:
                            tools = json.loads(tr["tools_used_json"])
                        except Exception:
                            tools = []
                    session.turns.append({
                        "id": tr.get("id"),
                        "timestamp": tr.get("timestamp"),
                        "user": tr.get("user_query"),
                        "agent": tr.get("agent_reply"),
                        "tools_used": tools,
                    })

                # Load commands from D1 commands table
                cmd_rows = self.db.execute("SELECT * FROM commands WHERE session_id = ? ORDER BY timestamp ASC", [session_id])
                for cr in cmd_rows:
                    session.executed_commands.append({
                        "id": cr.get("id"),
                        "timestamp": cr.get("timestamp"),
                        "command": cr.get("command"),
                        "returncode": cr.get("returncode", 0),
                        "output_preview": cr.get("output_preview", ""),
                    })

                self.active_session = session

                # Update index
                index = self._load_index()
                index["active_session_id"] = session_id
                self._save_index(index)
                return True
        except Exception:
            pass

        # 2. Fallback to local JSON file
        session_path = self.sessions_dir / f"{session_id}.json"
        if not session_path.exists():
            return False

        try:
            data = json.loads(session_path.read_text(encoding="utf-8"))
            self.active_session = AgenticSession.from_dict(data)
            
            # Sync into D1 for future lookups
            try:
                self.save()
            except Exception:
                pass

            index = self._load_index()
            index["active_session_id"] = session_id
            self._save_index(index)
            return True
        except Exception:
            return False

    def save(self) -> None:
        """Saves current active session to Cloudflare D1 and local backup."""
        if not self.active_session:
            return

        self.active_session.updated_at = time.strftime("%Y-%m-%d %H:%M:%S")

        # 1. Cloudflare D1 Update
        try:
            self.db.execute(
                """INSERT OR REPLACE INTO sessions 
                   (id, title, model, created_at, updated_at, last_status, plan_json, files_changed_json, verification_status_json, notes_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    self.active_session.session_id,
                    self.active_session.title,
                    self.active_session.model,
                    self.active_session.created_at,
                    self.active_session.updated_at,
                    self.active_session.last_status,
                    json.dumps(self.active_session.plan or {}),
                    json.dumps(self.active_session.files_changed or {}),
                    json.dumps(self.active_session.verification_status or {}),
                    json.dumps(self.active_session.notes or {}),
                ],
            )
        except Exception:
            pass

        # 2. Local File Backup
        self._save_file_backup()

    def _save_file_backup(self) -> None:
        """Writes active session to local JSON file and index."""
        if not self.active_session:
            return
        session_path = self.sessions_dir / f"{self.active_session.session_id}.json"
        try:
            session_path.write_text(json.dumps(self.active_session.to_dict(), indent=2), encoding="utf-8")
            index = self._load_index()
            for s in index.get("sessions", []):
                if s.get("session_id") == self.active_session.session_id:
                    s["title"] = self.active_session.title
                    s["updated_at"] = self.active_session.updated_at
                    s["turns_count"] = len(self.active_session.turns)
                    s["model"] = self.active_session.model
                    break
            self._save_index(index)
        except Exception:
            pass

    def list_sessions(self) -> List[Dict[str, Any]]:
        """Returns all sessions from Cloudflare D1 database or local index sorted by last updated."""
        # Try D1 database query
        try:
            rows = self.db.execute(
                """SELECT s.id as session_id, s.title, s.model, s.created_at, s.updated_at, s.last_status,
                          (SELECT COUNT(*) FROM turns WHERE session_id = s.id) as turns_count
                   FROM sessions s
                   ORDER BY s.updated_at DESC"""
            )
            if rows:
                return rows
        except Exception:
            pass

        # Fallback to local files & index
        index = self._load_index()
        sessions = index.get("sessions", [])

        valid = []
        for s in sessions:
            sid = s.get("session_id")
            if sid and (self.sessions_dir / f"{sid}.json").exists():
                valid.append(s)

        existing_ids = {s.get("session_id") for s in valid}
        for f in self.sessions_dir.glob("session_*.json"):
            sid = f.stem
            if sid not in existing_ids:
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    valid.append({
                        "session_id": sid,
                        "title": data.get("title", sid),
                        "created_at": data.get("created_at", ""),
                        "updated_at": data.get("updated_at", ""),
                        "turns_count": len(data.get("turns", [])),
                        "model": data.get("model", "")
                    })
                except Exception:
                    pass

        return valid

    def delete_session(self, session_id: str) -> bool:
        """Deletes a session and its associated turns, commands, and events from Cloudflare D1."""
        # 1. Cloudflare D1 deletion
        try:
            self.db.execute("DELETE FROM turns WHERE session_id = ?", [session_id])
            self.db.execute("DELETE FROM commands WHERE session_id = ?", [session_id])
            self.db.execute("DELETE FROM agentic_events WHERE session_id = ?", [session_id])
            self.db.execute("DELETE FROM sessions WHERE id = ?", [session_id])
        except Exception:
            pass

        # 2. Local file deletion
        session_path = self.sessions_dir / f"{session_id}.json"
        if session_path.exists():
            try:
                session_path.unlink()
            except Exception:
                pass

        index = self._load_index()
        index["sessions"] = [s for s in index.get("sessions", []) if s.get("session_id") != session_id]
        if index.get("active_session_id") == session_id:
            if index["sessions"]:
                index["active_session_id"] = index["sessions"][0]["session_id"]
                self.load_session(index["active_session_id"])
            else:
                index["active_session_id"] = None
                self.create_session("New Session")
        self._save_index(index)
        return True

    def record_turn(
        self,
        user_query: str,
        agent_reply: str = "",
        assistant_response: Optional[str] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        plan: Optional[Any] = None,
        files_changed: Optional[Dict[str, List[str]]] = None,
        verification_status: Optional[Dict[str, Any]] = None,
        status: str = "completed"
    ) -> Dict[str, Any]:
        """Records a completed turn into Cloudflare D1 turns table and updates session metadata."""
        if not self.active_session:
            self.create_session()

        effective_reply = agent_reply or assistant_response or ""

        # Generate automatic title from first turn
        if len(self.active_session.turns) == 0 and self.active_session.title in ("New Session", "Default Session", "Untitled Session"):
            clean_q = user_query.strip()
            first_line = clean_q.splitlines()[0] if clean_q else "Session"
            self.active_session.title = (first_line[:40] + "...") if len(first_line) > 40 else first_line

        turn_index = len(self.active_session.turns)
        turn_id = f"turn_{int(time.time()*1000)}_{turn_index}"
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

        turn = {
            "id": turn_id,
            "turn_index": turn_index,
            "timestamp": timestamp,
            "user": user_query,
            "agent": effective_reply,
            "tools_used": tool_calls or []
        }
        self.active_session.turns.append(turn)

        if plan is not None:
            self.active_session.set_plan(plan)
        if files_changed is not None:
            self.active_session.files_changed = files_changed
        if verification_status is not None:
            self.active_session.verification_status = verification_status
        self.active_session.last_status = status

        # Insert turn into Cloudflare D1 turns table
        try:
            self.db.execute(
                """INSERT INTO turns (id, session_id, turn_index, timestamp, user_query, agent_reply, tools_used_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    turn_id,
                    self.active_session.session_id,
                    turn_index,
                    timestamp,
                    user_query,
                    effective_reply,
                    json.dumps(tool_calls or []),
                ],
            )
        except Exception:
            pass

        self.save()
        return turn

    def record_command(self, command: str, returncode: int, output_preview: str) -> None:
        """Records an executed shell command into Cloudflare D1 commands table."""
        if not self.active_session:
            self.create_session()

        cmd_id = f"cmd_{int(time.time()*1000)}"
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

        self.active_session.executed_commands.append({
            "id": cmd_id,
            "timestamp": timestamp,
            "command": command,
            "returncode": returncode,
            "output_preview": output_preview[:200],
        })

        # Insert command into Cloudflare D1 commands table
        try:
            self.db.execute(
                """INSERT INTO commands (id, session_id, timestamp, command, returncode, output_preview)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    cmd_id,
                    self.active_session.session_id,
                    timestamp,
                    command,
                    returncode,
                    output_preview[:200],
                ],
            )
        except Exception:
            pass

        self.save()

    def get_recent_context(self, max_turns: int = 5) -> str:
        """Extracts recent conversation turns from the active session."""
        if not self.active_session:
            return ""
        turns = self.active_session.turns[-max_turns:]
        if not turns:
            return ""
        lines = [f"[Session: {self.active_session.title}]"]
        for t in turns:
            lines.append(f"User: {t.get('user')}")
            lines.append(f"Kratos: {t.get('agent')}")
        return "\n".join(lines)

    def clear(self) -> None:
        """Clears the active session's turns and history or starts a new session."""
        if self.active_session:
            try:
                self.db.execute("DELETE FROM turns WHERE session_id = ?", [self.active_session.session_id])
                self.db.execute("DELETE FROM commands WHERE session_id = ?", [self.active_session.session_id])
                self.db.execute("DELETE FROM agentic_events WHERE session_id = ?", [self.active_session.session_id])
            except Exception:
                pass
            self.active_session.turns = []
            self.active_session.executed_commands = []
            self.active_session.created_artifacts = []
            self.active_session.notes = {}
            self.save()


# Global memory singleton instance
memory = AgenticMemory()
