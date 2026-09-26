"""Deterministic mock providers for hermetic testing and orchestration verification (§58)."""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

from kratos_agent.core.runtime_contracts import ToolCall
from kratos_agent.providers.base import (
    AgentBackend,
    AgentCapabilities,
    AgentRun,
    AgentSession,
    ProviderCapabilityError,
    ProviderExecutionError,
    ProviderTimeout,
)
from kratos_agent.providers.events import (
    AgentEvent,
    CanonicalEventType,
    publish_agent_event,
)
from kratos_agent.providers.health import HealthStatus, ProviderHealth


class MockProvider(AgentBackend):
    """Standard predictable mock backend."""

    def __init__(
        self,
        name: str = "mock",
        output_text: str = "Mock execution completed.",
        response_text: str | None = None,
        tool_calls: list[ToolCall] | None = None,
        capabilities: AgentCapabilities | None = None,
    ) -> None:
        self._name = name
        self.output_text = response_text if response_text is not None else output_text
        self.mock_tool_calls = tool_calls or []
        self._capabilities = capabilities or AgentCapabilities(
            file_editing=True,
            shell_execution=True,
            git_workflows=True,
            streaming=True,
            image_input=True,
            subagents=True,
            tool_calling=True,
            mcp=True,
            session_persistence=True,
            steering=False,
            interruption=False,
            sandbox=True,
            long_running=True,
            reasoning=True,
        )
        self._sessions: dict[str, AgentSession] = {}
        self.execution_count = 0

    @property
    def name(self) -> str:
        return self._name

    def capabilities(self) -> AgentCapabilities:
        return self._capabilities

    async def start_session(
        self,
        task_id: str,
        session_id: str,
        context: dict[str, Any] | None = None,
    ) -> AgentSession:
        if session_id in self._sessions:
            return self._sessions[session_id]
        session = AgentSession(
            session_id=session_id,
            provider=self.name,
            provider_session_id=f"{self.name}_sess_123",
            metadata=context or {},
        )
        self._sessions[session_id] = session
        return session

    async def run(
        self,
        task_id: str,
        session_id: str = "",
        prompt: str = "",
        context: dict[str, Any] | None = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> AgentRun:
        self.execution_count += 1
        instruction = prompt or kwargs.get("instruction", "")
        effective_session_id = session_id or kwargs.get("session", {}).get("session_id", "default_sess")

        publish_agent_event(AgentEvent(
            task_id=task_id,
            session_id=effective_session_id,
            provider=self.name,
            event_type=CanonicalEventType.TASK_STARTED,
            payload={"instruction": instruction},
            narratable=True,
            voice_text=f"Mock task started by {self.name}",
        ))

        for tc in self.mock_tool_calls:
            publish_agent_event(AgentEvent(
                task_id=task_id,
                session_id=effective_session_id,
                provider=self.name,
                event_type=CanonicalEventType.TOOL_CALL_STARTED,
                payload={"tool": tc.name, "args": tc.arguments},
            ))

        run_res = AgentRun(
            task_id=task_id,
            session_id=effective_session_id,
            provider=self.name,
            output_text=self.output_text,
            tool_calls=list(self.mock_tool_calls),
            duration_seconds=0.05,
            status="completed",
        )

        publish_agent_event(AgentEvent(
            task_id=task_id,
            session_id=effective_session_id,
            provider=self.name,
            event_type=CanonicalEventType.TASK_COMPLETED,
            narratable=True,
            voice_text=f"Mock task completed by {self.name}",
        ))
        return run_res

    async def stream(
        self,
        task_id: str,
        session_id: str = "",
        prompt: str = "",
        context: dict[str, Any] | None = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[AgentEvent]:
        self.execution_count += 1
        effective_session_id = session_id or "default_sess"
        start_ev = AgentEvent(
            task_id=task_id,
            session_id=effective_session_id,
            provider=self.name,
            event_type=CanonicalEventType.TASK_STARTED,
        )
        publish_agent_event(start_ev)
        yield start_ev

        for word in self.output_text.split():
            delta_ev = AgentEvent(
                task_id=task_id,
                session_id=effective_session_id,
                provider=self.name,
                event_type=CanonicalEventType.ASSISTANT_DELTA,
                payload={"delta": word + " "},
            )
            publish_agent_event(delta_ev)
            yield delta_ev

        end_ev = AgentEvent(
            task_id=task_id,
            session_id=effective_session_id,
            provider=self.name,
            event_type=CanonicalEventType.TASK_COMPLETED,
        )
        publish_agent_event(end_ev)
        yield end_ev

    async def steer(self, task_id: str, instruction: str) -> None:
        raise ProviderCapabilityError(provider=self.name, message="Steering not supported by MockProvider")

    async def interrupt(self, task_id: str) -> None:
        raise ProviderCapabilityError(provider=self.name, message="Interruption not supported by MockProvider")

    async def close(self, session_id: str = "") -> None:
        if session_id:
            self._sessions.pop(session_id, None)
        else:
            self._sessions.clear()

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(provider=self.name, status=HealthStatus.READY, details="Mock ready")


class StreamingProvider(MockProvider):
    """Mock provider with explicit stream chunks."""

    def __init__(
        self,
        name: str = "streaming",
        stream_chunks: list[str] | None = None,
    ) -> None:
        chunks = stream_chunks or ["Chunk 1", "Chunk 2", "Chunk 3"]
        super().__init__(name=name, output_text="".join(chunks))
        self.stream_chunks = chunks

    async def stream(
        self,
        task_id: str,
        session_id: str = "",
        prompt: str = "",
        context: dict[str, Any] | None = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[AgentEvent]:
        self.execution_count += 1
        effective_session_id = session_id or "default_sess"

        start_ev = AgentEvent(
            task_id=task_id,
            session_id=effective_session_id,
            provider=self.name,
            event_type=CanonicalEventType.TASK_STARTED,
        )
        yield start_ev

        for chunk in self.stream_chunks:
            yield AgentEvent(
                task_id=task_id,
                session_id=effective_session_id,
                provider=self.name,
                event_type=CanonicalEventType.ASSISTANT_DELTA,
                payload={"delta": chunk},
            )

        yield AgentEvent(
            task_id=task_id,
            session_id=effective_session_id,
            provider=self.name,
            event_type=CanonicalEventType.TASK_COMPLETED,
        )


class FailingProvider(MockProvider):
    """Simulates failures and health degradation."""

    def __init__(
        self,
        name: str = "failing",
        fail_count: int = 3,
        error_message: str = "Simulated provider failure",
    ) -> None:
        super().__init__(name=name)
        self.remaining_failures = fail_count
        self.error_message = error_message

    async def run(self, *args: Any, **kwargs: Any) -> AgentRun:
        if self.remaining_failures > 0:
            self.remaining_failures -= 1
            raise ProviderExecutionError(provider=self.name, message=self.error_message)
        return await super().run(*args, **kwargs)

    async def health_check(self) -> ProviderHealth:
        if self.remaining_failures > 0:
            return ProviderHealth(provider=self.name, status=HealthStatus.OFFLINE, details=self.error_message)
        return ProviderHealth(provider=self.name, status=HealthStatus.READY, details="Recovered")


class InterruptibleProvider(MockProvider):
    """Mock provider with turn interruption support."""

    def __init__(self, name: str = "interruptible") -> None:
        caps = AgentCapabilities(interruption=True, streaming=True)
        super().__init__(name=name, capabilities=caps)
        self.interrupted_tasks: set[str] = set()

    async def interrupt(self, task_id: str) -> None:
        self.interrupted_tasks.add(task_id)

    async def stream(
        self,
        task_id: str,
        session_id: str = "",
        prompt: str = "",
        context: dict[str, Any] | None = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[AgentEvent]:
        self.execution_count += 1
        effective_session_id = session_id or "default_sess"

        yield AgentEvent(
            task_id=task_id,
            session_id=effective_session_id,
            provider=self.name,
            event_type=CanonicalEventType.TASK_STARTED,
        )

        if task_id in self.interrupted_tasks:
            yield AgentEvent(
                task_id=task_id,
                session_id=effective_session_id,
                provider=self.name,
                event_type=CanonicalEventType.TASK_INTERRUPTED,
                payload={"reason": "User interrupted"},
                voice_text="Task was interrupted.",
                narratable=True,
            )
            return

        yield AgentEvent(
            task_id=task_id,
            session_id=effective_session_id,
            provider=self.name,
            event_type=CanonicalEventType.TASK_COMPLETED,
        )


class SteerableProvider(MockProvider):
    """Mock provider with turn steering support."""

    def __init__(self, name: str = "steerable") -> None:
        caps = AgentCapabilities(steering=True)
        super().__init__(name=name, capabilities=caps)
        self.steered_tasks: dict[str, str] = {}

    async def steer(self, task_id: str, instruction: str) -> None:
        self.steered_tasks[task_id] = instruction
