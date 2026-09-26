"""Kimi Agent Backend Adapter (§17).

Integrates the Kimi Agent SDK / Moonshot AI for alternative coding runs,
second-opinion implementations, and parallel agent experiments.
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
from kratos_agent.providers.events import (
    AgentEvent,
    CanonicalEventType,
    EventSeverity,
    publish_agent_event,
)
from kratos_agent.providers.health import HealthStatus
from kratos_agent.providers.kimi.lifecycle import KimiSessionManager
from kratos_agent.providers.kimi.mapper import map_kimi_error
from kratos_agent.providers.tool_adapter import ToolAdapter

logger = logging.getLogger(__name__)


class KimiAdapter:
    """Pluggable agent backend for Kimi / Moonshot."""

    name = "kimi"

    def __init__(
        self,
        model: str = "moonshot-v1-32k",
        api_key: str | None = None,
        base_url: str = "https://api.moonshot.cn/v1",
        tool_adapter: ToolAdapter | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.getenv("KIMI_API_KEY") or os.getenv("MOONSHOT_API_KEY")
        self.base_url = os.getenv("MOONSHOT_BASE_URL", base_url)
        self.tools = tool_adapter or ToolAdapter()
        self.session_manager = KimiSessionManager()
        self._active_tasks: dict[str, bool] = {}

    def _is_sdk_installed(self) -> bool:
        return bool(
            importlib.util.find_spec("kimi")
            or importlib.util.find_spec("moonshot")
            or importlib.util.find_spec("openai")
        )

    def capabilities(self) -> AgentCapabilities:
        return AgentCapabilities(
            file_editing=True,
            shell_execution=True,
            git_workflows=True,
            streaming=True,
            image_input=False,
            subagents=True,
            tool_calling=True,
            mcp=True,
            session_persistence=True,
            steering=False,
            interruption=True,
            sandbox=False,
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
            raise ProviderUnavailable("Kimi SDK or OpenAI client is not installed.", provider=self.name)
        if not self.api_key:
            raise ProviderAuthenticationError("KIMI_API_KEY or MOONSHOT_API_KEY is not set.", provider=self.name)

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
            voice_text="Started task execution with Kimi.",
            voice_priority=1,
        ))

        try:
            import openai
            client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)
            kimi_tools = self.tools.to_openai_tools()

            messages = []
            if system_inst:
                messages.append({"role": "system", "content": system_inst})
            messages.append({"role": "user", "content": instruction})

            loop = asyncio.get_running_loop()

            def _call_kimi():
                return client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=kimi_tools,
                    timeout=timeout or 60.0,
                )

            response = await loop.run_in_executor(None, _call_kimi)
            choice = response.choices[0]
            output_text = choice.message.content or ""
            executed_calls: list[ToolCall] = []

            if choice.message.tool_calls:
                for tc_raw in choice.message.tool_calls:
                    import json
                    args = {}
                    try:
                        args = json.loads(tc_raw.function.arguments)
                    except Exception:
                        pass

                    tc = ToolCall(
                        name=tc_raw.function.name,
                        arguments=args,
                        call_id=tc_raw.id,
                    )
                    publish_agent_event(AgentEvent(
                        task_id=task_id,
                        session_id=session.session_id,
                        provider=self.name,
                        event_type=CanonicalEventType.TOOL_CALL_STARTED,
                        payload={"tool": tc.name, "args": tc.arguments},
                        voice_narratable=True,
                        voice_text=f"Kimi executing tool {tc.name}",
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
                voice_text="Kimi execution finished.",
            ))
            return run_res

        except Exception as exc:
            diag = map_kimi_error(exc)
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
            raise ProviderUnavailable("Kimi SDK is not installed.", provider=self.name)

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
            import openai
            client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)

            def _stream_call():
                stream_res = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        *([{"role": "system", "content": system_inst}] if system_inst else []),
                        {"role": "user", "content": instruction},
                    ],
                    stream=True,
                )
                for chunk in stream_res:
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content

            loop = asyncio.get_running_loop()
            deltas = await loop.run_in_executor(None, lambda: list(_stream_call()))

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
                "error": "Kimi SDK / OpenAI client not installed.",
            }
        if not self.api_key:
            return {
                "provider": self.name,
                "status": HealthStatus.DISABLED.value,
                "error": "KIMI_API_KEY environment variable not set.",
            }
        return {
            "provider": self.name,
            "status": HealthStatus.READY.value,
            "model": self.model,
        }
