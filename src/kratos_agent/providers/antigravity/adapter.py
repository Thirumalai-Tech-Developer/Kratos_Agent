"""Antigravity Python SDK Backend Adapter for Kratos Agent.

Integrates Google Antigravity SDK as an execution specialist backend behind
feature flags and capability probing.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from kratos_agent.providers.antigravity.lifecycle import AntigravityLifecycleManager
from kratos_agent.providers.antigravity.mapper import (
    map_antigravity_error,
    map_antigravity_thought_event,
    map_antigravity_token_event,
    map_antigravity_tool_call,
)
from kratos_agent.providers.base import (
    AgentBackend,
    AgentCapabilities,
    AgentRun,
    AgentSession,
    ProviderCapabilityError,
    ProviderUnavailable,
)
from kratos_agent.providers.context_bridge import ProviderContextBridge
from kratos_agent.providers.events import (
    AgentEvent,
    CanonicalEventType,
    redact_secrets,
)
from kratos_agent.providers.health import ProviderHealth

logger = logging.getLogger(__name__)


class AntigravityAdapter(AgentBackend):
    """Adapter for Google Antigravity Agent backend."""

    def __init__(
        self,
        enabled: bool = False,
        lifecycle_manager: AntigravityLifecycleManager | None = None,
        context_bridge: ProviderContextBridge | None = None,
    ) -> None:
        self._name = "antigravity"
        self.lifecycle = lifecycle_manager or AntigravityLifecycleManager(enabled=enabled)
        self.context_bridge = context_bridge or ProviderContextBridge()
        self._sessions: dict[str, AgentSession] = {}
        self._interrupted: set[str] = set()

    @property
    def name(self) -> str:
        return self._name

    def capabilities(self) -> AgentCapabilities:
        """Report verified capabilities for Antigravity Python SDK."""
        return AgentCapabilities(
            streaming=True,
            interruption=False,  # Task level cancellation handled via session close
            steering=False,
            image_input=False,
            local_tools=True,
            mcp=False,
            subagents=False,
            sandboxing=True,
            persistent_sessions=True,
            file_editing=True,
            shell_execution=True,
            git_workflows=True,
            long_running_runtime=False,
            max_context_tokens=1000000,
        )

    async def health_check(self) -> ProviderHealth:
        """Probe health status of Antigravity backend."""
        return self.lifecycle.probe_health()

    async def start_session(
        self,
        task_id: str,
        session_id: str,
        context: dict[str, Any] | None = None,
    ) -> AgentSession:
        """Start or retrieve an Antigravity agent session."""
        if not self.lifecycle.enabled or not self.lifecycle.is_available():
            raise ProviderUnavailable(
                provider=self.name,
                message="Antigravity backend is disabled or not installed on this system.",
            )

        if session_id in self._sessions:
            return self._sessions[session_id]

        system_prompt = ""
        if context:
            system_prompt = self.context_bridge.build_system_context(
                provider_name=self.name,
                user_instructions=context.get("system_prompt", ""),
            )

        try:
            agent = await self.lifecycle.create_agent(session_id, system_instructions=system_prompt)
            session = AgentSession(
                session_id=session_id,
                provider=self.name,
                provider_session_id=session_id,
                metadata={"agent": agent},
            )
            self._sessions[session_id] = session
            return session
        except Exception as e:
            raise map_antigravity_error(e, provider=self.name) from e

    async def run(
        self,
        task_id: str,
        session_id: str,
        prompt: str,
        context: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> AgentRun:
        """Execute a full task turn with Antigravity and collect output."""
        output_chunks: list[str] = []
        events: list[AgentEvent] = []

        async for event in self.stream(task_id, session_id, prompt, context, tools):
            events.append(event)
            if event.event_type == CanonicalEventType.ASSISTANT_DELTA:
                output_chunks.append(event.payload.get("delta", ""))

        final_content = "".join(output_chunks)
        return AgentRun(
            task_id=task_id,
            session_id=session_id,
            provider=self.name,
            status="completed",
            output=redact_secrets(final_content),
            events=events,
        )

    async def stream(
        self,
        task_id: str,
        session_id: str,
        prompt: str,
        context: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Stream response tokens and tool calls from Antigravity agent."""
        session = await self.start_session(task_id, session_id, context)
        agent = session.metadata.get("agent")
        if not agent:
            raise ProviderUnavailable(provider=self.name, message="Antigravity agent instance missing from session.")

        yield AgentEvent(
            task_id=task_id,
            session_id=session_id,
            provider=self.name,
            event_type=CanonicalEventType.TASK_STARTED,
            payload={"prompt_preview": redact_secrets(prompt[:100])},
            voice_text="Starting Antigravity task execution.",
            voice_priority=50,
            narratable=True,
        )

        try:
            # Send prompt and obtain response stream
            response = await agent.chat(prompt)

            # Check for tool calls or thoughts if exposed by response object
            if hasattr(response, "thoughts"):
                try:
                    async for thought in response.thoughts:
                        yield map_antigravity_thought_event(task_id, session_id, thought)
                except Exception as te:
                    logger.debug("Antigravity thoughts stream ended: %s", te)

            if hasattr(response, "tool_calls"):
                try:
                    async for call in response.tool_calls:
                        call_name = getattr(call, "name", "unknown")
                        call_args = getattr(call, "args", {})
                        yield map_antigravity_tool_call(task_id, session_id, call_name, call_args)
                except Exception as ce:
                    logger.debug("Antigravity tool calls stream ended: %s", ce)

            # Stream tokens
            async for token in response:
                if task_id in self._interrupted:
                    yield AgentEvent(
                        task_id=task_id,
                        session_id=session_id,
                        provider=self.name,
                        event_type=CanonicalEventType.TASK_INTERRUPTED,
                        payload={"reason": "User interrupted task."},
                        voice_text="Task interrupted.",
                        voice_priority=90,
                        narratable=True,
                    )
                    break

                yield map_antigravity_token_event(task_id, session_id, token)

            yield AgentEvent(
                task_id=task_id,
                session_id=session_id,
                provider=self.name,
                event_type=CanonicalEventType.TASK_COMPLETED,
                payload={"status": "completed"},
                voice_text="Antigravity execution finished.",
                voice_priority=60,
                narratable=True,
            )

        except Exception as e:
            mapped_err = map_antigravity_error(e, provider=self.name)
            yield AgentEvent(
                task_id=task_id,
                session_id=session_id,
                provider=self.name,
                event_type=CanonicalEventType.TASK_FAILED,
                payload={"error": str(mapped_err)},
                severity="error",
                voice_text="Antigravity execution failed.",
                voice_priority=100,
                narratable=True,
            )
            raise mapped_err from e

    async def steer(self, task_id: str, instruction: str) -> None:
        """Steering is not supported in Antigravity SDK."""
        raise ProviderCapabilityError(
            provider=self.name,
            message="Dynamic mid-turn steering is not supported by Antigravity Python SDK.",
        )

    async def interrupt(self, task_id: str) -> None:
        """Flag task for interruption and close stream."""
        self._interrupted.add(task_id)

    async def close(self, session_id: str) -> None:
        """Close an Antigravity agent session."""
        self._sessions.pop(session_id, None)
        await self.lifecycle.close_agent(session_id)
