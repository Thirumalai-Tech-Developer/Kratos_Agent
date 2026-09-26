"""Capability descriptor matrix, requirement matcher, and provider scoring engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .base import AgentCapabilities
from .health import HealthStatus, ProviderHealth


class CapabilityMatchResult(tuple):
    """3-tuple (is_compatible, score, reasons) that evaluates to is_compatible in bool context."""

    def __new__(cls, is_compatible: bool, score: float, reasons: list[str]):
        inst = super().__new__(cls, (is_compatible, score, reasons))
        inst._is_compatible = is_compatible
        return inst

    @property
    def is_compatible(self) -> bool:
        return self._is_compatible

    @property
    def score(self) -> float:
        return self[1]

    @property
    def reasons(self) -> list[str]:
        return self[2]

    def __bool__(self) -> bool:
        return self._is_compatible


class ProviderScore(tuple):
    """2-tuple (total_score, reasons) with attribute access for compatibility."""

    def __new__(
        cls,
        provider: str,
        total_score: float,
        is_compatible: bool,
        capability_score: float,
        latency_score: float,
        health_penalty: float,
        reasons: list[str],
    ):
        inst = super().__new__(cls, (total_score, reasons))
        inst.provider = provider
        inst.total_score = total_score
        inst.is_compatible = is_compatible
        inst.capability_score = capability_score
        inst.latency_score = latency_score
        inst.health_penalty = health_penalty
        inst.reasons = reasons
        return inst


@dataclass
class TaskRequirements:
    """Specific requirements demanded by a user task or workflow."""
    needs_file_editing: bool = False
    needs_shell_execution: bool = False
    needs_git_workflows: bool = False
    needs_streaming: bool = False
    needs_image_input: bool = False
    needs_subagents: bool = False
    needs_tool_calling: bool = False
    needs_mcp: bool = False
    needs_sandbox: bool = False
    needs_long_running: bool = False
    needs_reasoning: bool = False
    min_context_tokens: int = 8_000
    preferred_provider: str | None = None
    tags: list[str] = field(default_factory=list)

    def __init__(
        self,
        needs_file_editing: bool = False,
        needs_shell_execution: bool = False,
        needs_git_workflows: bool = False,
        needs_streaming: bool = False,
        needs_image_input: bool = False,
        needs_subagents: bool = False,
        needs_tool_calling: bool = False,
        needs_mcp: bool = False,
        needs_sandbox: bool = False,
        needs_long_running: bool = False,
        needs_reasoning: bool = False,
        min_context_tokens: int = 8_000,
        preferred_provider: str | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        self.needs_file_editing = kwargs.get("requires_file_editing", needs_file_editing)
        self.needs_shell_execution = kwargs.get("requires_shell_execution", needs_shell_execution)
        self.needs_git_workflows = kwargs.get("requires_git_workflows", needs_git_workflows)
        self.needs_streaming = kwargs.get("requires_streaming", needs_streaming)
        self.needs_image_input = kwargs.get("requires_vision", kwargs.get("requires_image_input", needs_image_input))
        self.needs_subagents = kwargs.get("requires_subagents", needs_subagents)
        self.needs_tool_calling = kwargs.get("requires_tools", kwargs.get("requires_tool_calling", needs_tool_calling))
        self.needs_mcp = kwargs.get("requires_mcp", needs_mcp)
        self.needs_sandbox = kwargs.get("requires_sandbox", needs_sandbox)
        self.needs_long_running = kwargs.get("requires_long_running", needs_long_running)
        self.needs_reasoning = kwargs.get("requires_reasoning", needs_reasoning)
        self.needs_steering = kwargs.get("requires_steering", False)
        self.needs_interruption = kwargs.get("requires_interruption", False)
        self.min_context_tokens = min_context_tokens
        self.preferred_provider = preferred_provider
        self.tags = tags or []


def _match_capabilities(
    caps: AgentCapabilities,
    reqs: TaskRequirements,
) -> tuple[bool, float, list[str]]:
    """Evaluates if provider capabilities satisfy task requirements and assigns a score."""
    reasons: list[str] = []
    incompatible = False
    score = 100.0

    checks = [
        (reqs.needs_file_editing, caps.file_editing, "File editing", 15.0),
        (reqs.needs_shell_execution, caps.shell_execution, "Shell execution", 15.0),
        (reqs.needs_git_workflows, caps.git_workflows, "Git workflows", 10.0),
        (reqs.needs_image_input, caps.image_input, "Vision / image perception input", 25.0),
        (reqs.needs_subagents, caps.subagents, "Subagent delegation", 10.0),
        (reqs.needs_tool_calling, caps.tool_calling, "Tool calling", 20.0),
        (reqs.needs_mcp, caps.mcp, "MCP protocol support", 15.0),
        (reqs.needs_sandbox, caps.sandbox, "Workspace sandboxing", 15.0),
        (reqs.needs_long_running, caps.long_running, "Long-running daemon runtime", 20.0),
        (reqs.needs_reasoning, caps.reasoning, "Deep reasoning / think mode", 15.0),
        (reqs.needs_streaming, caps.streaming, "Streaming", 10.0),
        (reqs.needs_steering, caps.steering, "Interactive turn steering", 15.0),
        (reqs.needs_interruption, caps.interruption, "Turn interruption", 10.0),
    ]

    for demanded, supported, label, weight in checks:
        if demanded:
            if not supported:
                reasons.append(f"Missing required capability: {label}")
                incompatible = True
                score -= weight * 2
            else:
                reasons.append(f"Supports {label} (+{weight:.0f})")
                score += weight

    if reqs.min_context_tokens > caps.max_context_tokens:
        reasons.append(
            f"Context window too small: {caps.max_context_tokens} < required {reqs.min_context_tokens}"
        )
        incompatible = True
        score -= 50.0

    return not incompatible, max(0.0, score), reasons


def evaluate_capability_match(
    caps: AgentCapabilities,
    reqs: TaskRequirements,
) -> bool:
    """Evaluates if provider capabilities satisfy task requirements strictly."""
    is_compatible, _, _ = _match_capabilities(caps, reqs)
    return is_compatible


def score_provider(
    provider_name: str,
    caps: AgentCapabilities,
    health_or_reqs: ProviderHealth | TaskRequirements,
    reqs: TaskRequirements | None = None,
    latency_ms: float = 0.0,
) -> ProviderScore:
    """Scores a provider based on capabilities, health, latency, and task fit."""
    if isinstance(health_or_reqs, TaskRequirements):
        actual_reqs = health_or_reqs
        health = ProviderHealth(provider=provider_name, status=HealthStatus.READY)
    else:
        actual_reqs = reqs or TaskRequirements()
        health = health_or_reqs

    is_compatible, cap_score, reasons = _match_capabilities(caps, actual_reqs)

    if not health.is_usable:
        reasons.append(f"Provider health unusable (status={health.status.value}, circuit={health.circuit_state.value})")
        return ProviderScore(
            provider=provider_name,
            total_score=0.0,
            is_compatible=False,
            capability_score=cap_score,
            latency_score=0.0,
            health_penalty=-1000.0,
            reasons=reasons,
        )

    # Latency scoring (lower latency yields higher score, up to 30 pts)
    lat = latency_ms or health.latency_ms or 500.0
    lat_score = max(0.0, 30.0 - (lat / 100.0))
    reasons.append(f"Latency score: {lat_score:.1f} (avg {lat:.0f}ms)")

    health_penalty = 0.0
    if health.status.value == "degraded":
        health_penalty = -25.0
        reasons.append("Degraded health status penalty (-25)")

    total = cap_score + lat_score + health_penalty

    # Preferred provider bonus
    if actual_reqs.preferred_provider and actual_reqs.preferred_provider.lower() == provider_name.lower():
        total += 50.0
        reasons.append("User requested preferred provider (+50)")

    return ProviderScore(
        provider=provider_name,
        total_score=round(max(0.0, total), 2),
        is_compatible=is_compatible,
        capability_score=round(cap_score, 2),
        latency_score=round(lat_score, 2),
        health_penalty=round(health_penalty, 2),
        reasons=reasons,
    )
