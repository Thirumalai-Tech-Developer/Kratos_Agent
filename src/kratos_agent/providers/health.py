"""Provider health checks, circuit breaker, and availability diagnostics."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class HealthStatus(str, Enum):
    READY = "ready"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    DISABLED = "disabled"


class CircuitState(str, Enum):
    CLOSED = "closed"       # Normal healthy operation
    HALF_OPEN = "half_open" # Testing provider recovery
    OPEN = "open"           # Tripped - traffic diverted to fallback


@dataclass
class ProviderHealth:
    provider: str
    status: HealthStatus = HealthStatus.OFFLINE
    latency_ms: float = 0.0
    last_checked: float = field(default_factory=time.time)
    circuit_state: CircuitState = CircuitState.CLOSED
    error: str | None = None
    version: str = "unknown"
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def is_usable(self) -> bool:
        return self.status in (HealthStatus.READY, HealthStatus.DEGRADED) and self.circuit_state != CircuitState.OPEN

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "status": self.status.value,
            "latency_ms": round(self.latency_ms, 2),
            "last_checked": self.last_checked,
            "circuit_state": self.circuit_state.value,
            "error": self.error,
            "version": self.version,
            "details": self.details,
            "is_usable": self.is_usable,
        }


class CircuitBreaker:
    """Protects against cascading failures when a provider encounters repeated faults (§49)."""

    def __init__(
        self,
        provider_name: str,
        failure_threshold: int = 3,
        recovery_cooldown_seconds: float = 30.0,
    ) -> None:
        self.provider_name = provider_name
        self.failure_threshold = failure_threshold
        self.recovery_cooldown_seconds = recovery_cooldown_seconds
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self.last_failure_time: float = 0.0
        self.success_count = 0

    def record_success(self) -> None:
        """Record successful operation and reset circuit breaker to healthy."""
        self.consecutive_failures = 0
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= 2:
                logger.info("Circuit breaker for %s reset to CLOSED (healthy).", self.provider_name)
                self.state = CircuitState.CLOSED
                self.success_count = 0
        else:
            self.state = CircuitState.CLOSED

    def record_failure(self, error: str | None = None) -> None:
        """Record a failure; trips to OPEN if threshold is crossed."""
        self.consecutive_failures += 1
        self.last_failure_time = time.time()
        logger.warning(
            "Provider %s failure count: %d/%d (%s)",
            self.provider_name,
            self.consecutive_failures,
            self.failure_threshold,
            error or "unspecified",
        )
        if self.consecutive_failures >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.error("Circuit breaker for %s TRIPPED to OPEN.", self.provider_name)

    def can_attempt(self) -> bool:
        """Check if request can proceed or if breaker is open."""
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            elapsed = time.time() - self.last_failure_time
            if elapsed >= self.recovery_cooldown_seconds:
                logger.info("Circuit breaker for %s transitioning from OPEN to HALF_OPEN.", self.provider_name)
                self.state = CircuitState.HALF_OPEN
                self.success_count = 0
                return True
            return False
        if self.state == CircuitState.HALF_OPEN:
            return True
        return False

    def can_execute(self) -> bool:
        """Alias for can_attempt."""
        return self.can_attempt()

    @property
    def failure_count(self) -> int:
        return self.consecutive_failures
