"""Lifecycle and runtime management for Antigravity Python SDK.

Isolates agent instantiation behind feature flags and verified capability probing.
"""

from __future__ import annotations

import logging
from typing import Any

from kratos_agent.providers.base import ProviderUnavailable
from kratos_agent.providers.health import HealthStatus, ProviderHealth

logger = logging.getLogger(__name__)


class AntigravityLifecycleManager:
    """Manages lifecycle of Google Antigravity Agent sessions."""

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self._active_agents: dict[str, Any] = {}

    def is_available(self) -> bool:
        """Probe if google.antigravity can be imported and runtime is verified."""
        if not self.enabled:
            return False
        try:
            import importlib.util
            spec = importlib.util.find_spec("google.antigravity")
            return spec is not None
        except Exception:
            return False

    def probe_health(self) -> ProviderHealth:
        """Probe health status of Antigravity SDK."""
        if not self.enabled:
            return ProviderHealth(
                provider="antigravity",
                status=HealthStatus.DISABLED,
                details="Antigravity backend is disabled in configuration.",
            )

        if not self.is_available():
            return ProviderHealth(
                provider="antigravity",
                status=HealthStatus.OFFLINE,
                details="google-antigravity package or runtime binary is not installed.",
            )

        return ProviderHealth(
            provider="antigravity",
            status=HealthStatus.READY,
            details="Google Antigravity SDK is installed and ready.",
        )

    async def create_agent(self, session_id: str, system_instructions: str = "") -> Any:
        """Create and enter an Antigravity Agent context manager if installed."""
        if not self.enabled:
            raise ProviderUnavailable(
                provider="antigravity",
                message="Antigravity backend is disabled by configuration.",
            )
        if not self.is_available():
            raise ProviderUnavailable(
                provider="antigravity",
                message="google-antigravity SDK is not installed or available on this system.",
            )

        try:
            from google.antigravity import Agent, CapabilitiesConfig, LocalAgentConfig

            config = LocalAgentConfig(
                system_instructions=system_instructions or "You are Kratos Antigravity specialist.",
                capabilities=CapabilitiesConfig(),
            )
            agent_cm = Agent(config)
            agent = await agent_cm.__aenter__()
            self._active_agents[session_id] = (agent, agent_cm)
            return agent
        except Exception as e:
            logger.error("Failed to initialize Antigravity agent: %s", e)
            raise ProviderUnavailable(
                provider="antigravity",
                message=f"Failed to start Antigravity agent: {e}",
                original_exception=e,
            ) from e

    async def close_agent(self, session_id: str) -> None:
        """Close an active Antigravity agent session cleanly."""
        entry = self._active_agents.pop(session_id, None)
        if entry:
            agent, agent_cm = entry
            try:
                await agent_cm.__aexit__(None, None, None)
            except Exception as e:
                logger.warning("Error exiting Antigravity agent context for session %s: %s", session_id, e)

    async def close_all(self) -> None:
        """Clean up all active Antigravity agent sessions."""
        for session_id in list(self._active_agents.keys()):
            await self.close_agent(session_id)
