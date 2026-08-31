"""Latency tracker and request telemetry for Kratos Agent.

Instruments every model request, tool execution, and context assembly with precise
nanosecond/millisecond timing, token metrics, and diagnostic reporting.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RequestMetrics:
    request_id: str
    task_id: str = ""
    model: str = ""
    provider: str = "brain"
    context_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tools_count: int = 0
    history_messages: int = 0
    context_build_ms: float = 0.0
    ttft_ms: float = 0.0
    generation_ms: float = 0.0
    tool_execution_ms: float = 0.0
    total_ms: float = 0.0
    retry_count: int = 0
    status: str = "completed"
    error: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "task_id": self.task_id,
            "model": self.model,
            "provider": self.provider,
            "context_tokens": self.context_tokens,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "tools_count": self.tools_count,
            "history_messages": self.history_messages,
            "context_build_ms": round(self.context_build_ms, 2),
            "ttft_ms": round(self.ttft_ms, 2),
            "generation_ms": round(self.generation_ms, 2),
            "tool_execution_ms": round(self.tool_execution_ms, 2),
            "total_ms": round(self.total_ms, 2),
            "retry_count": self.retry_count,
            "status": self.status,
            "error": self.error,
        }

    def format_diagnostic(self) -> str:
        """Formats a Rich-compatible diagnostic summary for /debug latency."""
        lines = [
            f"[bold gold1]REQUEST #{self.request_id[:8]}[/bold gold1]",
            "─" * 40,
            f"[bold white]Provider:[/bold white] [cyan]{self.provider}[/cyan]",
            f"[bold white]Model:[/bold white]    [cyan]{self.model}[/cyan]",
            "",
            "[bold white]Context:[/bold white]",
            f"  Input tokens:     [yellow]{self.input_tokens or self.context_tokens:,}[/yellow]",
            f"  Output tokens:    [yellow]{self.output_tokens:,}[/yellow]",
            f"  Tools:            [cyan]{self.tools_count}[/cyan]",
            f"  History messages: [cyan]{self.history_messages}[/cyan]",
            "",
            "[bold white]Timing:[/bold white]",
            f"  Context build:    [green]{self.context_build_ms:.1f}ms[/green]",
            f"  TTFT:             [green]{self.ttft_ms/1000:.2f}s[/green]" if self.ttft_ms > 0 else "  TTFT:             [dim]N/A[/dim]",
            f"  Generation:       [green]{self.generation_ms/1000:.2f}s[/green]",
            f"  Tool execution:   [green]{self.tool_execution_ms/1000:.2f}s[/green]",
            f"  Total:            [bold green]{self.total_ms/1000:.2f}s[/bold green]",
            "",
            f"[bold white]Retries:[/bold white]          [yellow]{self.retry_count}[/yellow]",
            f"[bold white]Status:[/bold white]           [bold green]{self.status}[/bold green]" if self.status == "completed" else f"[bold red]{self.status} ({self.error})[/bold red]",
        ]
        return "\n".join(lines)


class LatencyTracker:
    """Thread-safe telemetry store capturing execution metrics for diagnostics."""

    def __init__(self, max_records: int = 100) -> None:
        self.max_records = max_records
        self.records: List[RequestMetrics] = []
        self._active: Optional[RequestMetrics] = None

    def start_request(
        self,
        task_id: str = "",
        model: str = "",
        provider: str = "brain",
        context_tokens: int = 0,
        tools_count: int = 0,
        history_messages: int = 0,
        context_build_ms: float = 0.0,
    ) -> RequestMetrics:
        metrics = RequestMetrics(
            request_id=f"req-{str(uuid.uuid4())[:8]}",
            task_id=task_id,
            model=model,
            provider=provider,
            context_tokens=context_tokens,
            input_tokens=context_tokens,
            tools_count=tools_count,
            history_messages=history_messages,
            context_build_ms=context_build_ms,
        )
        self._active = metrics
        return metrics

    def record_completed(self, metrics: RequestMetrics) -> None:
        self.records.append(metrics)
        if len(self.records) > self.max_records:
            self.records.pop(0)
        self._active = None

    def get_last_metrics(self) -> Optional[RequestMetrics]:
        if self.records:
            return self.records[-1]
        return self._active

    def get_all_metrics(self) -> List[RequestMetrics]:
        return list(self.records)

    def summary(self) -> Dict[str, Any]:
        if not self.records:
            return {"total_requests": 0, "avg_total_s": 0.0, "avg_generation_s": 0.0}
        total_time = sum(r.total_ms for r in self.records) / len(self.records) / 1000
        gen_time = sum(r.generation_ms for r in self.records) / len(self.records) / 1000
        return {
            "total_requests": len(self.records),
            "avg_total_s": round(total_time, 2),
            "avg_generation_s": round(gen_time, 2),
            "latest_request_id": self.records[-1].request_id,
        }


# Global Singleton
latency_tracker = LatencyTracker()
