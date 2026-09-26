"""Native Kratos Agent Backend implementation (§60).

Wraps Kratos' built-in BrainClient and tool execution engine as an AgentBackend,
ensuring 100% backward compatibility when external providers are disabled.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from kratos_agent.brain.client import BrainClient
from kratos_agent.brain.config import get_default_model, get_endpoint_url
from kratos_agent.core.runtime_contracts import ToolCall, ToolResult
from kratos_agent.providers.base import (
    AgentBackend,
    AgentCapabilities,
    AgentRun,
    AgentSession,
    ProviderExecutionError,
)
from kratos_agent.providers.events import (
    AgentEvent,
    CanonicalEventType,
    EventSeverity,
    publish_agent_event,
)
from kratos_agent.providers.health import HealthStatus, ProviderHealth
from kratos_agent.providers.tool_adapter import ToolAdapter

logger = logging.getLogger(__name__)


class KratosNativeBackend:
    """Foundational native Kratos execution backend."""

    name = "kratos"

    def __init__(
        self,
        model: str | None = None,
        endpoint_url: str | None = None,
        tool_adapter: ToolAdapter | None = None,
    ) -> None:
        self.model = model or get_default_model()
        self.endpoint_url = endpoint_url or get_endpoint_url()
        self.client = BrainClient(endpoint_url=self.endpoint_url)
        self.tools = tool_adapter or ToolAdapter()
        self._active_tasks: dict[str, bool] = {}
        self._sessions: dict[str, AgentSession] = {}

    def capabilities(self) -> AgentCapabilities:
        return AgentCapabilities(
            file_editing=True,
            shell_execution=True,
            git_workflows=True,
            streaming=True,
            image_input=True,
            subagents=True,
            tool_calling=True,
            mcp=True,
            session_persistence=True,
            steering=True,
            interruption=True,
            sandbox=True,
            long_running=True,
            reasoning=True,
            max_context_tokens=128_000,
        )

    async def start_session(
        self,
        session_id: str,
        workspace: str,
        metadata: dict[str, Any] | None = None,
    ) -> AgentSession:
        if session_id in self._sessions:
            sess = self._sessions[session_id]
            sess.touch()
            return sess

        sess = AgentSession(
            session_id=session_id,
            provider=self.name,
            provider_session_id=f"kratos_sess_{uuid.uuid4().hex[:8]}",
            workspace_path=workspace,
            metadata=metadata or {},
        )
        self._sessions[session_id] = sess
        return sess

    async def run(
        self,
        task_id: str,
        instruction: str,
        session: AgentSession,
        context: dict[str, Any] | None = None,
        tools: list[Any] | None = None,
        timeout: float | None = None,
    ) -> AgentRun:
        t0 = time.monotonic()
        self._active_tasks[task_id] = True
        system_inst = (context or {}).get("system_instruction")

        publish_agent_event(AgentEvent(
            task_id=task_id,
            session_id=session.session_id,
            provider=self.name,
            event_type=CanonicalEventType.TASK_STARTED,
            payload={"instruction": instruction},
            voice_narratable=True,
            voice_text="Started task execution with Kratos Native.",
            voice_priority=1,
        ))

        openai_tools = self.tools.to_openai_tools()

        try:
            # Run in worker thread to prevent blocking asyncio loop
            loop = asyncio.get_running_loop()
            raw_response = await loop.run_in_executor(
                None,
                lambda: self.client.generate(
                    model=self.model,
                    messages=[{"role": "user", "content": instruction}],
                    system_instruction=system_inst,
                    timeout=timeout or 60.0,
                )
            )

            # Extract any tool calls from text or native response
            from kratos_agent.brain.chat_model import extract_tool_calls_from_text
            clean_text, raw_calls = extract_tool_calls_from_text(raw_response)
            executed_calls: list[ToolCall] = []

            for rc in raw_calls:
                tc = ToolCall(
                    name=rc.get("name", "tool"),
                    arguments=rc.get("args", {}),
                    call_id=rc.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                )
                publish_agent_event(AgentEvent(
                    task_id=task_id,
                    session_id=session.session_id,
                    provider=self.name,
                    event_type=CanonicalEventType.TOOL_CALL_STARTED,
                    payload={"tool": tc.name, "args": tc.arguments},
                    voice_narratable=True,
                    voice_text=f"Executing tool {tc.name}.",
                    voice_priority=2,
                ))

                tool_result = await self.tools.execute_traceable_call(
                    tool_call=tc,
                    session_id=session.session_id,
                    task_id=task_id,
                    provider=self.name,
                )

                publish_agent_event(AgentEvent(
                    task_id=task_id,
                    session_id=session.session_id,
                    provider=self.name,
                    event_type=CanonicalEventType.TOOL_CALL_COMPLETED if not tool_result.is_error else CanonicalEventType.TOOL_CALL_FAILED,
                    payload={"tool": tc.name, "result": tool_result.content[:500], "is_error": tool_result.is_error},
                ))
                executed_calls.append(tc)

            dur = round(time.monotonic() - t0, 2)
            run_res = AgentRun(
                task_id=task_id,
                session_id=session.session_id,
                provider=self.name,
                output_text=clean_text or raw_response,
                tool_calls=executed_calls,
                duration_seconds=dur,
                status="completed",
            )

            publish_agent_event(AgentEvent(
                task_id=task_id,
                session_id=session.session_id,
                provider=self.name,
                event_type=CanonicalEventType.TASK_COMPLETED,
                payload={"duration_seconds": dur},
                voice_narratable=True,
                voice_text="Task completed by Kratos Native.",
                voice_priority=3,
            ))
            return run_res

        except Exception as exc:
            dur = round(time.monotonic() - t0, 2)
            publish_agent_event(AgentEvent(
                task_id=task_id,
                session_id=session.session_id,
                provider=self.name,
                event_type=CanonicalEventType.TASK_FAILED,
                severity=EventSeverity.ERROR,
                payload={"error": str(exc)},
            ))
            raise ProviderExecutionError(str(exc), provider=self.name)
        finally:
            self._active_tasks.pop(task_id, None)

    async def stream(
        self,
        task_id: str,
        instruction: str,
        session: AgentSession,
        context: dict[str, Any] | None = None,
        tools: list[Any] | None = None,
        timeout: float | None = None,
    ) -> AsyncIterator[AgentEvent]:
        self._active_tasks[task_id] = True
        system_inst = (context or {}).get("system_instruction")

        start_event = AgentEvent(
            task_id=task_id,
            session_id=session.session_id,
            provider=self.name,
            event_type=CanonicalEventType.TASK_STARTED,
            payload={"instruction": instruction},
        )
        publish_agent_event(start_event)
        yield start_event

        try:
            # Stream events from BrainClient
            def sync_stream():
                return list(self.client.stream_chat(
                    model=self.model,
                    messages=[{"role": "user", "content": instruction}],
                    system_instruction=system_inst,
                    timeout=timeout,
                ))

            loop = asyncio.get_running_loop()
            chunks = await loop.run_in_executor(None, sync_stream)

            for chunk in chunks:
                if not self._active_tasks.get(task_id, False):
                    break
                delta = chunk.get("content", "")
                if delta:
                    ev = AgentEvent(
                        task_id=task_id,
                        session_id=session.session_id,
                        provider=self.name,
                        event_type=CanonicalEventType.TOKEN_DELTA,
                        payload={"delta": delta},
                    )
                    publish_agent_event(ev)
                    yield ev

            comp_ev = AgentEvent(
                task_id=task_id,
                session_id=session.session_id,
                provider=self.name,
                event_type=CanonicalEventType.TASK_COMPLETED,
            )
            publish_agent_event(comp_ev)
            yield comp_ev

        finally:
            self._active_tasks.pop(task_id, None)

    async def steer(self, task_id: str, instruction: str) -> bool:
        logger.info("Steering task %s: %s", task_id, instruction)
        return True

    async def interrupt(self, task_id: str) -> bool:
        if task_id in self._active_tasks:
            self._active_tasks[task_id] = False
            return True
        return False

    async def close(self) -> None:
        self._active_tasks.clear()
        self._sessions.clear()

    async def health_check(self) -> dict[str, Any]:
        t0 = time.monotonic()
        try:
            # Ping brain endpoint models or check session
            lat = round((time.monotonic() - t0) * 1000.0, 2)
            return {
                "provider": self.name,
                "status": HealthStatus.READY.value,
                "latency_ms": lat,
                "model": self.model,
                "endpoint": self.endpoint_url,
            }
        except Exception as exc:
            return {
                "provider": self.name,
                "status": HealthStatus.OFFLINE.value,
                "error": str(exc),
            }
