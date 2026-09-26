"""Performance telemetry, latency budgeting, and profiling for Kratos Agent."""
from __future__ import annotations

import logging
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

logger = logging.getLogger("kratos.perf")

LATENCY_BUDGET: dict[str, float] = {
    "routing_ms": 50.0,
    "memory_ms": 100.0,
    "observation_ms": 150.0,
    "tool_ms": 500.0,
    "llm_ms": 2500.0,
}


@dataclass
class PerformanceMetrics:
    # Latencies in milliseconds
    route_ms: float = 0.0
    memory_ms: float = 0.0
    observe_ms: float = 0.0
    llm_ms: float = 0.0
    tool_ms: float = 0.0
    total_ms: float = 0.0

    # Token usage
    prompt_tokens: int = 0
    completion_tokens: int = 0
    memory_tokens: int = 0

    # Counts
    tool_count: int = 0
    observation_count: int = 0
    retries: int = 0
    memory_hits: int = 0
    memory_injected: int = 0
    cache_hits: int = 0
    cache_misses: int = 0

    def format_log(self) -> str:
        """Formats a compact log line matching §4."""
        return (
            f"[PERF] route={self.route_ms:.0f}ms memory={self.memory_ms:.0f}ms "
            f"observe={self.observe_ms:.0f}ms llm={self.llm_ms:.0f}ms "
            f"tool={self.tool_ms:.0f}ms total={self.total_ms:.0f}ms"
        )

    def format_summary(self) -> str:
        """Formats detailed performance summary matching §45."""
        llm_sec = self.llm_ms / 1000.0
        tot_sec = self.total_ms / 1000.0
        return (
            "KRATOS PERFORMANCE\n\n"
            f"LLM:\n"
            f"  prompt: {self.prompt_tokens:,} tokens\n"
            f"  completion: {self.completion_tokens:,} tokens\n"
            f"  latency: {llm_sec:.2f}s\n\n"
            f"Memory:\n"
            f"  retrieval: {self.memory_ms:.0f}ms\n"
            f"  hits: {self.memory_hits}\n"
            f"  injected: {self.memory_injected}\n\n"
            f"Computer:\n"
            f"  observations: {self.observation_count}\n"
            f"  tool calls: {self.tool_count}\n"
            f"  retries: {self.retries}\n"
            f"  cache hits: {self.cache_hits}\n"
            f"  cache misses: {self.cache_misses}\n\n"
            f"Total:\n"
            f"  {tot_sec:.2f}s"
        )


class Profiler:
    """Manages performance measurement for an agent turn or task."""

    def __init__(self) -> None:
        self.metrics = PerformanceMetrics()
        self._start_time = time.monotonic()

    @contextmanager
    def measure(self, phase: str) -> Generator[None, None, None]:
        t0 = time.monotonic()
        try:
            yield
        finally:
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            if phase == "route":
                self.metrics.route_ms += elapsed_ms
            elif phase == "memory":
                self.metrics.memory_ms += elapsed_ms
            elif phase == "observe":
                self.metrics.observe_ms += elapsed_ms
                self.metrics.observation_count += 1
            elif phase == "llm":
                self.metrics.llm_ms += elapsed_ms
            elif phase == "tool":
                self.metrics.tool_ms += elapsed_ms
                self.metrics.tool_count += 1

    def finish(self) -> PerformanceMetrics:
        self.metrics.total_ms = (time.monotonic() - self._start_time) * 1000.0
        logger.info(self.metrics.format_log())
        return self.metrics


_current_profiler: Profiler | None = None


def get_active_profiler() -> Profiler:
    global _current_profiler
    if _current_profiler is None:
        _current_profiler = Profiler()
    return _current_profiler


def reset_active_profiler() -> Profiler:
    global _current_profiler
    _current_profiler = Profiler()
    return _current_profiler
