"""Kimi session and lifecycle management (§17)."""
from __future__ import annotations

import uuid
from typing import Any

from kratos_agent.providers.base import AgentSession


class KimiSessionManager:
    """Manages mapped Kimi SDK sessions."""

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

        kimi_sess_id = f"kimi_sess_{uuid.uuid4().hex[:12]}"
        sess = AgentSession(
            session_id=session_id,
            provider="kimi",
            provider_session_id=kimi_sess_id,
            workspace_path=workspace,
            metadata=metadata or {},
        )
        self._sessions[session_id] = sess
        return sess

    def close_all(self) -> None:
        self._sessions.clear()
