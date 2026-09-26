"""Kratos Beast Multi-SDK Execution Fabric & Provider Orchestration.

Unified autonomous agent platform capable of selecting and coordinating multiple
high-quality agent runtimes (Claude, Codex, Kimi, DeepSeek, Antigravity, Kratos Native)
while preserving one consistent user-facing identity, one task model, one event model,
one memory system, and one verification pipeline.
"""

from kratos_agent.providers.base import (
    AgentBackend,
    AgentCapabilities,
    AgentRun,
    AgentSession,
    ProviderAuthenticationError,
    ProviderCancelled,
    ProviderCapabilityError,
    ProviderConfigurationError,
    ProviderContextError,
    ProviderError,
    ProviderExecutionError,
    ProviderProtocolError,
    ProviderRateLimitError,
    ProviderTimeout,
    ProviderUnavailable,
)
from kratos_agent.providers.capabilities import (
    TaskRequirements,
    evaluate_capability_match,
    score_provider,
)
from kratos_agent.providers.context_bridge import ProviderContextBridge
from kratos_agent.providers.diagnostics import (
    inspect_provider,
    render_provider_doctor,
)
from kratos_agent.providers.events import (
    AgentEvent,
    CanonicalEventType,
    publish_agent_event,
    redact_secrets,
)
from kratos_agent.providers.gemini_live_bridge import (
    GeminiLiveBridge,
    VisualContextSnapshot,
    VisualSource,
)
from kratos_agent.providers.health import (
    CircuitBreaker,
    CircuitState,
    HealthStatus,
    ProviderHealth,
)
from kratos_agent.providers.kratos_native import KratosNativeBackend
from kratos_agent.providers.registry import ProviderRegistry
from kratos_agent.providers.router import (
    ExecutionMode,
    ProviderRouter,
    ResourceLockManager,
    ReviewFinding,
    RoutingDecision,
    RoutingPolicy,
)
from kratos_agent.providers.tool_adapter import ToolAdapter

__all__ = [
    # Core Interfaces & Types
    "AgentBackend",
    "AgentCapabilities",
    "AgentRun",
    "AgentSession",
    # Error Hierarchy
    "ProviderError",
    "ProviderUnavailable",
    "ProviderTimeout",
    "ProviderAuthenticationError",
    "ProviderProtocolError",
    "ProviderCapabilityError",
    "ProviderExecutionError",
    "ProviderRateLimitError",
    "ProviderCancelled",
    "ProviderContextError",
    "ProviderConfigurationError",
    # Health & Circuit Breaker
    "HealthStatus",
    "ProviderHealth",
    "CircuitBreaker",
    "CircuitState",
    # Capabilities & Requirements
    "TaskRequirements",
    "evaluate_capability_match",
    "score_provider",
    # Events & Redaction
    "AgentEvent",
    "CanonicalEventType",
    "publish_agent_event",
    "redact_secrets",
    # Tools & Context
    "ToolAdapter",
    "ProviderContextBridge",
    # Registry & Native Backend
    "KratosNativeBackend",
    "ProviderRegistry",
    # Router & Orchestration
    "ProviderRouter",
    "ExecutionMode",
    "RoutingPolicy",
    "ReviewFinding",
    "RoutingDecision",
    "ResourceLockManager",
    # Gemini Live Bridge
    "GeminiLiveBridge",
    "VisualContextSnapshot",
    "VisualSource",
    # Diagnostics
    "render_provider_doctor",
    "inspect_provider",
]
