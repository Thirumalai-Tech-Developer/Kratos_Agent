"""Debug panel — renders the full event trace for /debug command.

Shows every RuntimeEvent from the last agent turn with:
  - Event kind & timestamp
  - Turn ID
  - Payload summary (with secrets redacted)
  - Full tool output (not collapsed like the live view)
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

console = Console()


def _safe_json(payload: Dict[str, Any]) -> str:
    """JSON-dump payload with secrets redacted."""
    _SECRET_KEYS = {
        "api_key", "authorization", "access_token", "refresh_token",
        "client_secret", "password", "token", "bearer",
    }

    def clean(v: Any, k: str = "") -> Any:
        if k.lower() in _SECRET_KEYS:
            return "[REDACTED]"
        if isinstance(v, dict):
            return {ck: clean(cv, ck) for ck, cv in v.items()}
        if isinstance(v, list):
            return [clean(i) for i in v]
        return v

    try:
        cleaned = clean(payload)
        return json.dumps(cleaned, indent=2, ensure_ascii=False, default=str)
    except Exception as e:
        return f"<serialization error: {e}>"


# ─── Event log display ────────────────────────────────────────────────────────

def render_event_log(events: List[Dict[str, Any]]) -> None:
    """Render full event trace as a scrollable panel with a summary table."""
    if not events:
        console.print("[dim]No events recorded for this turn.[/dim]\n")
        return

    table = Table(
        title="[bold gold1]⊡ Full Execution Event Trace[/bold gold1]",
        border_style="dim cyan",
        show_header=True,
        header_style="bold cyan",
        expand=True,
    )
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Kind", style="bold white", min_width=22)
    table.add_column("Turn ID", style="dim", width=10)
    table.add_column("Δt (s)", style="dim", justify="right", width=8)
    table.add_column("Payload Summary", style="dim white")

    _KIND_COLORS = {
        "turn.started":            "dim cyan",
        "model.request_assembled": "cyan",
        "model.response":          "bold cyan",
        "tool.requested":          "gold1",
        "tool.completed":          "green",
        "tool.failed":             "bold red",
        "context.compacted":       "yellow",
        "runtime.retry":           "yellow",
        "turn.completed":          "bold green",
        "turn.failed":             "bold red",
    }

    base_ts: float = events[0].get("timestamp", time.time()) if events else time.time()

    for i, ev in enumerate(events):
        kind = ev.get("kind", "?")
        turn_id = ev.get("turn_id", "")[:8]
        ts = ev.get("timestamp", base_ts)
        delta = f"{ts - base_ts:.3f}"
        payload = ev.get("payload", {})

        # Build a short summary of key fields
        summary_parts = []
        if "name" in payload:
            summary_parts.append(f"name={payload['name']}")
        if "finish_reason" in payload:
            summary_parts.append(f"finish={payload['finish_reason']}")
        if "steps" in payload:
            summary_parts.append(f"steps={payload['steps']}")
        if "error" in payload:
            err = str(payload["error"])[:60]
            summary_parts.append(f"error={err}")
        if "usage" in payload and payload["usage"]:
            u = payload["usage"]
            total = u.get("total_tokens") or u.get("totalTokens") or 0
            if total:
                summary_parts.append(f"tokens={total}")
        if "tool_calls" in payload and payload["tool_calls"]:
            summary_parts.append(f"calls={len(payload['tool_calls'])}")
        if "message_count" in payload:
            summary_parts.append(f"history={payload['message_count']}")

        summary = "  ".join(summary_parts) if summary_parts else "—"
        color = _KIND_COLORS.get(kind, "white")
        table.add_row(
            str(i),
            Text(kind, style=color),
            turn_id,
            delta,
            summary,
        )

    console.print()
    console.print(table)
    console.print()


def render_full_event_detail(events: List[Dict[str, Any]], event_idx: Optional[int] = None) -> None:
    """Render full JSON detail for a single event or all events."""
    from typing import Optional as Opt
    target_events = [events[event_idx]] if event_idx is not None and 0 <= event_idx < len(events) else events
    for i, ev in enumerate(target_events):
        kind = ev.get("kind", "?")
        payload_json = _safe_json(ev.get("payload", {}))
        console.print(Panel(
            Syntax(payload_json, "json", theme="monokai", line_numbers=False),
            title=f"[bold cyan]Event #{i}: {kind}[/bold cyan]",
            border_style="dim cyan",
            padding=(0, 1),
        ))


def render_step_log(steps: List[Any]) -> None:
    """Render full step log from EventRenderer.steps for /debug."""
    if not steps:
        console.print("[dim]No steps recorded.[/dim]\n")
        return

    table = Table(
        title="[bold gold1]⊡ Agent Step Log[/bold gold1]",
        border_style="dim cyan",
        show_header=True,
        header_style="bold cyan",
        expand=True,
    )
    table.add_column("#", width=3, justify="right", style="dim")
    table.add_column("Status", width=12, style="bold")
    table.add_column("Label", min_width=24)
    table.add_column("Detail", style="dim white")
    table.add_column("Duration", width=8, justify="right", style="dim")
    table.add_column("Output Lines", width=12, justify="right", style="dim")

    STATUS_COLORS = {
        "thinking":  "cyan",
        "running":   "gold1",
        "success":   "green",
        "failed":    "bold red",
        "retry":     "yellow",
        "cancelled": "red",
        "done":      "bold white",
    }

    for step in steps:
        color = STATUS_COLORS.get(step.status, "white")
        out_lines = len(step.tool_output.splitlines()) if step.tool_output else 0
        out_str = str(out_lines) + ("+" if step.output_truncated else "") if out_lines else "—"

        table.add_row(
            str(step.index),
            Text(step.status.upper(), style=color),
            step.label,
            step.detail[:70] if step.detail else "",
            step.duration or "—",
            out_str,
        )

    console.print()
    console.print(table)

    # Show full tool output for any step that has it
    for step in steps:
        if step.tool_output:
            title = f"[bold cyan]Step #{step.index} output: {step.label}[/bold cyan]"
            content = step.tool_output
            if step.output_truncated:
                content += "\n[dim]… (output was truncated in live view)[/dim]"
            console.print(Panel(
                content,
                title=title,
                border_style="dim",
                padding=(0, 1),
            ))

    console.print()


def render_latency_report() -> None:
    """Renders the detailed latency breakdown and request timing diagnostic."""
    from kratos_agent.core.latency_tracker import latency_tracker
    metrics = latency_tracker.get_last_metrics()
    if not metrics:
        console.print("[dim]No latency metrics recorded yet.[/dim]\n")
        return
    console.print()
    console.print(Panel(
        metrics.format_diagnostic(),
        title="[bold gold1]⚡ Model & Pipeline Latency Diagnostics[/bold gold1]",
        border_style="gold1",
        padding=(1, 2),
    ))
    console.print()
