"""DeepSeek Harness Home, Profiles, and Runtime Lifecycle Management (§18)."""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

from kratos_agent.providers.base import AgentSession

logger = logging.getLogger(__name__)


class DeepSeekLifecycleManager:
    """Manages isolated .kratos/providers/deepseek state directory and harness profiles."""

    def __init__(self, base_workspace: Path | None = None) -> None:
        self.workspace = base_workspace or Path.cwd()
        self.dsh_home = self.workspace / ".kratos" / "providers" / "deepseek"
        self.profiles_dir = self.dsh_home / "profiles"
        self.sessions_dir = self.dsh_home / "sessions"
        self.runtime_dir = self.dsh_home / "runtime"
        self.logs_dir = self.dsh_home / "logs"

        self._sessions: dict[str, AgentSession] = {}
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        for p in (self.profiles_dir, self.sessions_dir, self.runtime_dir, self.logs_dir):
            p.mkdir(parents=True, exist_ok=True)

    def get_or_create_session(
        self,
        session_id: str,
        workspace: str,
        profile_name: str = "default",
        metadata: dict[str, Any] | None = None,
    ) -> AgentSession:
        """Creates or reuses a per-profile session under isolated DSH home."""
        if session_id in self._sessions:
            sess = self._sessions[session_id]
            sess.touch()
            return sess

        profile_path = self.profiles_dir / profile_name
        profile_path.mkdir(parents=True, exist_ok=True)

        dsh_session_id = f"dsh_{profile_name}_{session_id[:8]}"
        sess_dir = self.sessions_dir / dsh_session_id
        sess_dir.mkdir(parents=True, exist_ok=True)

        sess = AgentSession(
            session_id=session_id,
            provider="deepseek",
            provider_session_id=dsh_session_id,
            workspace_path=workspace,
            metadata={
                **(metadata or {}),
                "dsh_home": str(self.dsh_home),
                "profile": profile_name,
                "profile_dir": str(profile_path),
            },
        )
        self._sessions[session_id] = sess
        return sess

    def get_runtime_env(self) -> dict[str, str]:
        """Configures environment pointing explicitly to Kratos-isolated DSH home (§18)."""
        env = os.environ.copy()
        env["DSH_HOME"] = str(self.dsh_home)
        env["DEEPSEEK_HARNESS_HOME"] = str(self.dsh_home)
        return env

    def clean_runtime(self) -> None:
        """Performs clean shutdown and purges ephemeral runtime state without touching logs."""
        try:
            if self.runtime_dir.exists():
                for item in self.runtime_dir.iterdir():
                    if item.is_file():
                        item.unlink(missing_ok=True)
                    elif item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
        except Exception as exc:
            logger.debug("Runtime cleanup note: %s", exc)

    def close_all(self) -> None:
        self.clean_runtime()
        self._sessions.clear()
