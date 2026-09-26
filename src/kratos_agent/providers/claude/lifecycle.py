"""Claude session and lifecycle management (§15)."""
from __future__ import annotations

import time
import uuid
from typing import Any

from kratos_agent.providers.base import AgentSession


class ClaudeSessionManager:
    """Manages mapped Claude SDK sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, AgentSession] = {}

    def get_or_create_session(
        self,
        session_id: str,
        workspace: str,
        metadata: dict[str, Any] | None = None,
    ) -> AgentSession:
        if session_id in self._sessions:
            sess = self._sessions[session_id]
            sess.touch()
            return sess

        claude_sess_id = f"claude_sess_{uuid.uuid4().hex[:12]}"
        sess = AgentSession(
            session_id=session_id,
            provider="claude",
            provider_session_id=claude_sess_id,
            workspace_path=workspace,
            metadata=metadata or {},
        )
        self._sessions[session_id] = sess
        return sess

    def close_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def close_all(self) -> None:
        self._sessions.clear()
