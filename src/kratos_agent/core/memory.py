from __future__ import annotations

import os
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

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
            "notes": self.notes
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
        return session

class AgenticMemory:
    """Manages multi-session persistent agent memory, command logs, and context isolation."""

    def __init__(self, sessions_dir: Optional[Path] = None):
        self.sessions_dir = sessions_dir or SESSIONS_DIR
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.sessions_dir / "index.json"
        
        self.active_session: Optional[AgenticSession] = None
        self._init_or_load_latest()

    def _init_or_load_latest(self):
        """Loads the most recent active session, migrates legacy memory, or initializes a new session."""
        index = self._load_index()
        if index.get("active_session_id"):
            loaded = self.load_session(index["active_session_id"])
            if loaded:
                return

        # Check if any sessions exist
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
        """Creates and activates a new persistent session."""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        short_id = uuid.uuid4().hex[:6]
        session_id = f"session_{timestamp}_{short_id}"
        session_title = title or f"Session {time.strftime('%b %d, %H:%M')}"

        session = AgenticSession(session_id=session_id, title=session_title, model=model)
        self.active_session = session
        
        # Save session file
        self.save()

        # Update index
        index = self._load_index()
        index["active_session_id"] = session_id
        session_entry = {
            "session_id": session_id,
            "title": session_title,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "turns_count": 0,
            "model": model
        }
        # Prepend to list
        index["sessions"] = [s for s in index.get("sessions", []) if s.get("session_id") != session_id]
        index["sessions"].insert(0, session_entry)
        self._save_index(index)

        return session

    def load_session(self, session_id: str) -> bool:
        """Loads a session from disk by its ID."""
        session_path = self.sessions_dir / f"{session_id}.json"
        if not session_path.exists():
            return False

        try:
            data = json.loads(session_path.read_text(encoding="utf-8"))
            self.active_session = AgenticSession.from_dict(data)
            
            # Update active ID in index
            index = self._load_index()
            index["active_session_id"] = session_id
            self._save_index(index)
            return True
        except Exception:
            return False

    def save(self) -> None:
        """Saves current active session to disk."""
        if not self.active_session:
            return
        
        self.active_session.updated_at = time.strftime("%Y-%m-%d %H:%M:%S")
        session_path = self.sessions_dir / f"{self.active_session.session_id}.json"
        try:
            session_path.write_text(json.dumps(self.active_session.to_dict(), indent=2), encoding="utf-8")
            
            # Update entry in index
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
        """Returns all sessions sorted by last updated."""
        index = self._load_index()
        sessions = index.get("sessions", [])
        
        # Verify files exist on disk
        valid = []
        for s in sessions:
            sid = s.get("session_id")
            if sid and (self.sessions_dir / f"{sid}.json").exists():
                valid.append(s)
        
        # If files exist that aren't in index, add them
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
        """Deletes a session file and updates index."""
        session_path = self.sessions_dir / f"{session_id}.json"
        if session_path.exists():
            try:
                session_path.unlink()
            except Exception:
                return False

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

    def record_turn(self, user_query: str, agent_reply: str, tool_calls: Optional[List[Dict[str, Any]]] = None) -> None:
        """Records a completed turn into the active session."""
        if not self.active_session:
            self.create_session()

        # Generate automatic title from first turn if title is default
        if len(self.active_session.turns) == 0 and self.active_session.title in ("New Session", "Default Session", "Untitled Session"):
            clean_q = user_query.strip()
            first_line = clean_q.splitlines()[0] if clean_q else "Session"
            self.active_session.title = (first_line[:40] + "...") if len(first_line) > 40 else first_line

        turn = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "user": user_query,
            "agent": agent_reply,
            "tools_used": tool_calls or []
        }
        self.active_session.turns.append(turn)
        self.save()

    def record_command(self, command: str, returncode: int, output_preview: str) -> None:
        """Records an executed shell command into the active session."""
        if not self.active_session:
            self.create_session()

        self.active_session.executed_commands.append({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "command": command,
            "returncode": returncode,
            "output_preview": output_preview[:200]
        })
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
            self.active_session.turns = []
            self.active_session.executed_commands = []
            self.active_session.created_artifacts = []
            self.active_session.notes = {}
            self.save()

# Global memory singleton instance
memory = AgenticMemory()
