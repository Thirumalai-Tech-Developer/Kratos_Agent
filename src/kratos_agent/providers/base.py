"""Provider-neutral agent backend interface and domain contracts for Kratos.

Kratos is the orchestrator. External provider runtimes (Claude, Codex, Kimi,
DeepSeek, Antigravity) are pluggable specialists conforming to this contract.
"""
from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from kratos_agent.core.runtime_contracts import ToolCall, ToolResult


class ProviderState(str, Enum):
    UNINITIALIZED = "uninitialized"
    INITIALIZING = "initializing"
    READY = "ready"
    BUSY = "busy"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    DISABLED = "disabled"


@dataclass(frozen=True)
class AgentCapabilities:
    """Runtime-discoverable capabilities of a provider backend."""
    file_editing: bool = True
    shell_execution: bool = True
    git_workflows: bool = False
    streaming: bool = True
    image_input: bool = False
    subagents: bool = False
    tool_calling: bool = True
    mcp: bool = False
    session_persistence: bool = True
    steering: bool = False
    interruption: bool = False
    sandbox: bool = False
    long_running: bool = False
    reasoning: bool = False
    max_context_tokens: int = 128_000

    def __init__(
        self,
        file_editing: bool = True,
        shell_execution: bool = True,
        git_workflows: bool = False,
        streaming: bool = True,
        image_input: bool = False,
        subagents: bool = False,
        tool_calling: bool = True,
        mcp: bool = False,
        session_persistence: bool = True,
        steering: bool = False,
        interruption: bool = False,
        sandbox: bool = False,
        long_running: bool = False,
        reasoning: bool = False,
        max_context_tokens: int = 128_000,
        **kwargs: Any,
    ) -> None:
        tc = kwargs.get("local_tools", tool_calling)
        sb = kwargs.get("sandboxing", sandbox)
        lr = kwargs.get("long_running_runtime", long_running)
        sp = kwargs.get("persistent_sessions", session_persistence)
        object.__setattr__(self, "file_editing", file_editing)
        object.__setattr__(self, "shell_execution", shell_execution)
        object.__setattr__(self, "git_workflows", git_workflows)
        object.__setattr__(self, "streaming", streaming)
        object.__setattr__(self, "image_input", image_input)
        object.__setattr__(self, "subagents", subagents)
        object.__setattr__(self, "tool_calling", tc)
        object.__setattr__(self, "mcp", mcp)
        object.__setattr__(self, "session_persistence", sp)
        object.__setattr__(self, "steering", steering)
        object.__setattr__(self, "interruption", interruption)
        object.__setattr__(self, "sandbox", sb)
        object.__setattr__(self, "long_running", lr)
        object.__setattr__(self, "reasoning", reasoning)
        object.__setattr__(self, "max_context_tokens", max_context_tokens)

    @property
    def local_tools(self) -> bool:
        return self.tool_calling

    @property
    def sandboxing(self) -> bool:
        return self.sandbox

    @property
    def long_running_runtime(self) -> bool:
        return self.long_running

    @property
    def persistent_sessions(self) -> bool:
        return self.session_persistence

    def supports(self, requirement: str) -> bool:
        """Check if capability flag is enabled."""
        return bool(getattr(self, requirement, False))

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_editing": self.file_editing,
            "shell_execution": self.shell_execution,
            "git_workflows": self.git_workflows,
            "streaming": self.streaming,
            "image_input": self.image_input,
            "subagents": self.subagents,
            "tool_calling": self.tool_calling,
            "mcp": self.mcp,
            "session_persistence": self.session_persistence,
            "steering": self.steering,
            "interruption": self.interruption,
            "sandbox": self.sandbox,
            "long_running": self.long_running,
            "reasoning": self.reasoning,
            "max_context_tokens": self.max_context_tokens,
        }


@dataclass
class AgentSession:
    """Correlation mapping between Kratos session and external provider session."""
    session_id: str
    provider: str
    provider_session_id: str
    workspace_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_active_at: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.last_active_at = time.time()


@dataclass
class AgentRun:
    """Outcome of a provider task execution."""
    task_id: str
    session_id: str
    provider: str
    output_text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tokens_used: dict[str, int] = field(default_factory=dict)
    duration_seconds: float = 0.0
    status: str = "completed"  # completed, failed, cancelled, interrupted
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def output(self) -> str:
        return self.output_text

    @output.setter
    def output(self, value: str) -> None:
        self.output_text = value

    @property
    def is_success(self) -> bool:
        return self.status == "completed" and self.error is None


# ---------------------------------------------------------------------------
# Unified Error Taxonomy (§47)
# ---------------------------------------------------------------------------

class ProviderError(Exception):
    """Base class for all provider-related errors."""
    def __init__(self, message: str, provider: str = "unknown", details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.details = details or {}


class ProviderUnavailable(ProviderError):
    """Provider SDK is not installed or service is currently unreachable."""


class ProviderTimeout(ProviderError):
    """Provider execution or request exceeded timeout budget."""


class ProviderAuthenticationError(ProviderError):
    """Provider rejected credentials or API key is missing."""


class ProviderProtocolError(ProviderError):
    """Provider returned malformed, invalid, or unexpected payload."""


class ProviderCapabilityError(ProviderError):
    """Requested operation is not supported by this provider."""


class ProviderExecutionError(ProviderError):
    """Provider failed during task execution."""


class ProviderRateLimitError(ProviderError):
    """Provider HTTP 429 or quota limit exceeded."""


class ProviderCancelled(ProviderError):
    """Task was cancelled or interrupted."""


class ProviderContextError(ProviderError):
    """Context window exceeded or payload too large for provider."""


class ProviderConfigurationError(ProviderError):
    """Invalid provider settings, model name, or initialization parameters."""


# ---------------------------------------------------------------------------
# Provider Contract Protocol (§3)
# ---------------------------------------------------------------------------

@runtime_checkable
class AgentBackend(Protocol):
    """Provider-neutral backend protocol for all execution runtimes."""

    name: str

    async def start_session(
        self,
        session_id: str,
        workspace: str,
        metadata: dict[str, Any] | None = None,
    ) -> AgentSession:
        """Initialize or reuse a provider session tied to a Kratos session."""
        ...

    async def run(
        self,
        task_id: str,
        instruction: str,
        session: AgentSession,
        context: dict[str, Any] | None = None,
        tools: list[Any] | None = None,
        timeout: float | None = None,
    ) -> AgentRun:
        """Execute a task to completion returning structured output and tool calls."""
        ...

    async def stream(
        self,
        task_id: str,
        instruction: str,
        session: AgentSession,
        context: dict[str, Any] | None = None,
        tools: list[Any] | None = None,
        timeout: float | None = None,
    ) -> AsyncIterator[Any]:
        """Stream normalized agent events from the provider."""
        ...

    async def steer(self, task_id: str, instruction: str) -> bool:
        """Inject steering direction into an active turn."""
        ...

    async def interrupt(self, task_id: str) -> bool:
        """Interrupt and halt an ongoing execution."""
        ...

    async def close(self) -> None:
        """Cleanly terminate provider sessions and free resources."""
        ...

    def capabilities(self) -> AgentCapabilities:
        """Return runtime capabilities supported by this provider backend."""
        ...

    async def health_check(self) -> dict[str, Any]:
        """Probe provider availability, latency, and auth status."""
        ...


# ---------------------------------------------------------------------------
# Execution Fabric Aliases (Kratos has ONE model; SDKs are Execution Backends)
# ---------------------------------------------------------------------------
ExecutionCapabilities = AgentCapabilities
ExecutionSession = AgentSession
ExecutionResult = AgentRun
ExecutionBackend = AgentBackend

