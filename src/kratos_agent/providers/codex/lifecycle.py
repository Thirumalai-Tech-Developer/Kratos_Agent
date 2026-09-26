"""Codex Thread, Turn, and session lifecycle management (§16)."""
from __future__ import annotations

import time
import uuid
from typing import Any

from kratos_agent.providers.base import AgentSession


class CodexSessionManager:
    """Manages mapped Codex threads and active turns."""

    def __init__(self) -> None:
        self._threads: dict[str, str] = {}  # session_id -> thread_id
        self._active_turns: dict[str, str] = {}  # task_id -> turn_id
        self._sessions: dict[str, AgentSession] = {}

    def get_or_create_thread(
        self,
        session_id: str,
        workspace: str,
        metadata: dict[str, Any] | None = None,
    ) -> AgentSession:
        if session_id in self._sessions:
            sess = self._sessions[session_id]
            sess.touch()
            return sess

        thread_id = f"thread_{uuid.uuid4().hex[:16]}"
        self._threads[session_id] = thread_id

        sess = AgentSession(
            session_id=session_id,
            provider="codex",
            provider_session_id=thread_id,
            workspace_path=workspace,
            metadata=metadata or {},
        )
        self._sessions[session_id] = sess
        return sess

    def register_turn(self, task_id: str) -> str:
        turn_id = f"turn_{uuid.uuid4().hex[:12]}"
        self._active_turns[task_id] = turn_id
        return turn_id

    def complete_turn(self, task_id: str) -> None:
        self._active_turns.pop(task_id, None)

    def close_all(self) -> None:
        self._threads.clear()
        self._active_turns.clear()
        self._sessions.clear()
