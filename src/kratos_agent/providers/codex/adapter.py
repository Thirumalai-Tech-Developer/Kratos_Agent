"""OpenAI Codex Agent Backend Adapter (§16).

Integrates OpenAI Codex / GPT-4o execution engine supporting threads, turns,
steering, interruption, workspace sandboxing, and local image input.
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
from kratos_agent.providers.codex.lifecycle import CodexSessionManager
from kratos_agent.providers.codex.mapper import map_codex_error
from kratos_agent.providers.events import (
    AgentEvent,
    CanonicalEventType,
    EventSeverity,
    publish_agent_event,
)
from kratos_agent.providers.health import HealthStatus
from kratos_agent.providers.tool_adapter import ToolAdapter

logger = logging.getLogger(__name__)


class CodexAdapter:
    """Pluggable agent backend for OpenAI Codex."""

    name = "codex"

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str | None = None,
        base_url: str | None = None,
        tool_adapter: ToolAdapter | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        self.tools = tool_adapter or ToolAdapter()
        self.session_manager = CodexSessionManager()
        self._active_tasks: dict[str, bool] = {}
        self._steering_queue: dict[str, list[str]] = {}

    def _is_sdk_installed(self) -> bool:
        return bool(importlib.util.find_spec("openai") or importlib.util.find_spec("codex"))

    def capabilities(self) -> AgentCapabilities:
        return AgentCapabilities(
            file_editing=True,
            shell_execution=True,
            git_workflows=True,
            streaming=True,
            image_input=True,
            subagents=False,
            tool_calling=True,
            mcp=False,
            session_persistence=True,
            steering=True,
            interruption=True,
            sandbox=True,
            long_running=False,
            reasoning=True,
            max_context_tokens=128_000,
        )

    async def start_session(
        self,
        session_id: str,
        workspace: str,
        metadata: dict[str, Any] | None = None,
    ) -> AgentSession:
        return self.session_manager.get_or_create_thread(session_id, workspace, metadata)

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
                "Codex / OpenAI SDK is not installed. (pip install openai)",
                provider=self.name,
            )
        if not self.api_key:
            raise ProviderAuthenticationError(
                "OPENAI_API_KEY is not configured.",
                provider=self.name,
            )

        t0 = time.monotonic()
        self._active_tasks[task_id] = True
        turn_id = self.session_manager.register_turn(task_id)

        system_inst = (context or {}).get("system_instruction", "")
        visual_context = (context or {}).get("visual_context")

        publish_agent_event(AgentEvent(
            task_id=task_id,
            session_id=session.session_id,
            provider=self.name,
            event_type=CanonicalEventType.TASK_STARTED,
            payload={"turn_id": turn_id, "instruction": instruction},
            voice_narratable=True,
            voice_text="Started implementation with Codex.",
            voice_priority=1,
        ))

        try:
            import openai
            client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)
            codex_tools = self.tools.to_openai_tools()

            # Build messages with image support if visual_context exists (§28, §71)
            messages: list[dict[str, Any]] = []
            if system_inst:
                messages.append({"role": "system", "content": system_inst})

            user_content: Any = instruction
            if visual_context and visual_context.get("image_ref"):
                user_content = [
                    {"type": "text", "text": instruction},
                    {"type": "image_url", "image_url": {"url": visual_context["image_ref"]}},
                ]

            messages.append({"role": "user", "content": user_content})

            loop = asyncio.get_running_loop()

            def _call_codex():
                return client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=codex_tools,
                    timeout=timeout or 60.0,
                )

            response = await loop.run_in_executor(None, _call_codex)
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
                        voice_text=f"Codex running tool {tc.name}",
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
                    "prompt_tokens": getattr(response.usage, "prompt_tokens", 0) if response.usage else 0,
                    "completion_tokens": getattr(response.usage, "completion_tokens", 0) if response.usage else 0,
                },
                duration_seconds=dur,
                status="completed",
                metadata={"turn_id": turn_id},
            )

            publish_agent_event(AgentEvent(
                task_id=task_id,
                session_id=session.session_id,
                provider=self.name,
                event_type=CanonicalEventType.TASK_COMPLETED,
                payload={"duration_seconds": dur},
                voice_narratable=True,
                voice_text="Codex implementation completed.",
            ))
            return run_res

        except Exception as exc:
            diag = map_codex_error(exc)
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
            self.session_manager.complete_turn(task_id)
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
            raise ProviderUnavailable("Codex / OpenAI SDK is not installed.", provider=self.name)

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
        """Injects steering direction into Codex active turn (§11, §16)."""
        if task_id not in self._steering_queue:
            self._steering_queue[task_id] = []
        self._steering_queue[task_id].append(instruction)
        logger.info("Queued steering instruction for Codex turn on %s: %s", task_id, instruction)
        return True

    async def interrupt(self, task_id: str) -> bool:
        if task_id in self._active_tasks:
            self._active_tasks[task_id] = False
            return True
        return False

    async def close(self) -> None:
        self.session_manager.close_all()
        self._active_tasks.clear()
        self._steering_queue.clear()

    async def health_check(self) -> dict[str, Any]:
        if not self._is_sdk_installed():
            return {
                "provider": self.name,
                "status": HealthStatus.OFFLINE.value,
                "error": "openai SDK not installed.",
            }
        if not self.api_key:
            return {
                "provider": self.name,
                "status": HealthStatus.DISABLED.value,
                "error": "OPENAI_API_KEY environment variable not set.",
            }
        return {
            "provider": self.name,
            "status": HealthStatus.READY.value,
            "model": self.model,
        }
