"""Claude Agent Backend Adapter (§15).

Integrates the Anthropic Claude Agent SDK as a pluggable specialist for reasoning,
architecture review, and tool calling via Kratos ToolAdapter and MCP bridge.
"""
from __future__ import annotations

import asyncio
import importlib
import logging
import os
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from kratos_agent.core.runtime_contracts import ToolCall
from kratos_agent.providers.base import (
    AgentBackend,
    AgentCapabilities,
    AgentRun,
    AgentSession,
    ProviderAuthenticationError,
    ProviderExecutionError,
    ProviderUnavailable,
)
from kratos_agent.providers.claude.lifecycle import ClaudeSessionManager
from kratos_agent.providers.claude.mapper import map_claude_error
from kratos_agent.providers.events import (
    AgentEvent,
    CanonicalEventType,
    EventSeverity,
    publish_agent_event,
)
from kratos_agent.providers.health import HealthStatus
from kratos_agent.providers.tool_adapter import ToolAdapter

logger = logging.getLogger(__name__)


class ClaudeAdapter:
    """Pluggable agent backend for Anthropic Claude."""

    name = "claude"

    def __init__(
        self,
        model: str = "claude-3-7-sonnet-20250219",
        api_key: str | None = None,
        tool_adapter: ToolAdapter | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.tools = tool_adapter or ToolAdapter()
        self.session_manager = ClaudeSessionManager()
        self._active_tasks: dict[str, bool] = {}

    def _is_sdk_installed(self) -> bool:
        return bool(importlib.util.find_spec("anthropic") or importlib.util.find_spec("claude_agent_sdk"))

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
            steering=False,
            interruption=True,
            sandbox=False,
            long_running=False,
            reasoning=True,
            max_context_tokens=200_000,
        )

    async def start_session(
        self,
        session_id: str,
        workspace: str,
        metadata: dict[str, Any] | None = None,
    ) -> AgentSession:
        return self.session_manager.get_or_create_session(session_id, workspace, metadata)

    async def run(
        self,
        task_id: str,
        instruction: str,
        session: AgentSession,
        context: dict[str, Any] | None = None,
        tools: list[Any] | None = None,
        timeout: float | None = None,
    ) -> AgentRun:
        if not self._is_sdk_installed():
            raise ProviderUnavailable(
                "Claude Agent SDK (anthropic) is not installed. Install with `pip install anthropic`.",
                provider=self.name,
            )
        if not self.api_key:
            raise ProviderAuthenticationError(
                "ANTHROPIC_API_KEY is not configured.",
                provider=self.name,
            )

        t0 = time.monotonic()
        self._active_tasks[task_id] = True
        system_inst = (context or {}).get("system_instruction", "")

        publish_agent_event(AgentEvent(
            task_id=task_id,
            session_id=session.session_id,
            provider=self.name,
            event_type=CanonicalEventType.TASK_STARTED,
            payload={"instruction": instruction},
            voice_narratable=True,
            voice_text="Started task execution with Claude.",
            voice_priority=1,
        ))

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)
            claude_tools = self.tools.to_claude_tools()

            # Execute run in threadpool
            loop = asyncio.get_running_loop()

            def _call_claude():
                return client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=system_inst,
                    messages=[{"role": "user", "content": instruction}],
                    tools=claude_tools,
                    timeout=timeout or 60.0,
                )

            message = await loop.run_in_executor(None, _call_claude)

            output_text = ""
            executed_calls: list[ToolCall] = []

            for block in message.content:
                if block.type == "text":
                    output_text += block.text
                elif block.type == "tool_use":
                    tc = ToolCall(
                        name=block.name,
                        arguments=block.input if isinstance(block.input, dict) else {},
                        call_id=block.id,
                    )
                    publish_agent_event(AgentEvent(
                        task_id=task_id,
                        session_id=session.session_id,
                        provider=self.name,
                        event_type=CanonicalEventType.TOOL_CALL_STARTED,
                        payload={"tool": tc.name, "args": tc.arguments},
                        voice_narratable=True,
                        voice_text=f"Claude calling tool {tc.name}",
                    ))
                    res = await self.tools.execute_traceable_call(
                        tool_call=tc,
                        session_id=session.session_id,
                        task_id=task_id,
                        provider=self.name,
                    )
                    publish_agent_event(AgentEvent(
                        task_id=task_id,
                        session_id=session.session_id,
                        provider=self.name,
                        event_type=CanonicalEventType.TOOL_CALL_COMPLETED if not res.is_error else CanonicalEventType.TOOL_CALL_FAILED,
                        payload={"tool": tc.name, "result": res.content[:500], "is_error": res.is_error},
                    ))
                    executed_calls.append(tc)

            dur = round(time.monotonic() - t0, 2)
            run_res = AgentRun(
                task_id=task_id,
                session_id=session.session_id,
                provider=self.name,
                output_text=output_text,
                tool_calls=executed_calls,
                tokens_used={
                    "input_tokens": getattr(message.usage, "input_tokens", 0),
                    "output_tokens": getattr(message.usage, "output_tokens", 0),
                },
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
                voice_text="Task completed by Claude.",
            ))
            return run_res

        except Exception as exc:
            diag = map_claude_error(exc)
            publish_agent_event(AgentEvent(
                task_id=task_id,
                session_id=session.session_id,
                provider=self.name,
                event_type=CanonicalEventType.TASK_FAILED,
                severity=EventSeverity.ERROR,
                payload=diag,
            ))
            raise ProviderExecutionError(str(exc), provider=self.name, details=diag)
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
        if not self._is_sdk_installed():
            raise ProviderUnavailable("Claude Agent SDK is not installed.", provider=self.name)

        self._active_tasks[task_id] = True
        system_inst = (context or {}).get("system_instruction", "")

        start_ev = AgentEvent(
            task_id=task_id,
            session_id=session.session_id,
            provider=self.name,
            event_type=CanonicalEventType.TASK_STARTED,
        )
        publish_agent_event(start_ev)
        yield start_ev

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)

            def _get_stream():
                with client.messages.stream(
                    model=self.model,
                    max_tokens=4096,
                    system=system_inst,
                    messages=[{"role": "user", "content": instruction}],
                ) as stream_ctx:
                    for text_delta in stream_ctx.text_stream:
                        yield text_delta

            loop = asyncio.get_running_loop()
            deltas = await loop.run_in_executor(None, lambda: list(_get_stream()))

            for delta in deltas:
                if not self._active_tasks.get(task_id, False):
                    break
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
        # Claude API does not natively support mid-turn steering
        return False

    async def interrupt(self, task_id: str) -> bool:
        if task_id in self._active_tasks:
            self._active_tasks[task_id] = False
            return True
        return False

    async def close(self) -> None:
        self.session_manager.close_all()
        self._active_tasks.clear()

    async def health_check(self) -> dict[str, Any]:
        if not self._is_sdk_installed():
            return {
                "provider": self.name,
                "status": HealthStatus.OFFLINE.value,
                "error": "anthropic SDK not installed. (pip install anthropic)",
            }
        if not self.api_key:
            return {
                "provider": self.name,
                "status": HealthStatus.DISABLED.value,
                "error": "ANTHROPIC_API_KEY environment variable not set.",
            }
        return {
            "provider": self.name,
            "status": HealthStatus.READY.value,
            "model": self.model,
        }
