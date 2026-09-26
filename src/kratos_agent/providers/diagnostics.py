"""Provider diagnostic and inspection utilities for Kratos Beast CLI.

Implements `python -m kratos_agent providers doctor` and interactive
`/providers` diagnostics without leaking credentials or private keys.
"""

from __future__ import annotations

import importlib.util
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from kratos_agent.providers.health import HealthStatus
from kratos_agent.providers.registry import ProviderRegistry


def render_provider_doctor(console: Console | None = None) -> Table:
    """Renders the comprehensive multi-SDK provider doctor table."""
    table = Table(title="⚔️ KRATOS BEAST // MULTI-SDK EXECUTION FABRIC DOCTOR", border_style="gold1")
    table.add_column("Provider", style="bold white", width=18)
    table.add_column("Status", width=14)
    table.add_column("Installed Version", style="dim", width=20)
    table.add_column("Key Capabilities", style="cyan", width=32)
    table.add_column("Health / Runtime Details", style="white")

    registry = ProviderRegistry.get_instance()
    providers = registry.list_providers()

    status_styles = {
        HealthStatus.READY: "[bold green]READY[/bold green]",
        HealthStatus.DEGRADED: "[bold yellow]DEGRADED[/bold yellow]",
        HealthStatus.OFFLINE: "[dim red]OFFLINE / MISSING[/dim red]",
        HealthStatus.DISABLED: "[dim]DISABLED[/dim]",
    }

    # Detect package versions
    pkg_versions = {}
    for pkg in ["openai", "anthropic", "google.genai", "google.antigravity"]:
        try:
            mod = __import__(pkg.split(".")[0])
            pkg_versions[pkg] = getattr(mod, "__version__", "installed")
        except Exception:
            pkg_versions[pkg] = "not installed"

    for name, backend in providers.items():
        health = registry.health_check(name)
        cb = registry.circuit_breaker(name)
        caps = backend.capabilities()

        # Build capabilities summary
        cap_list = []
        if caps.streaming:
            cap_list.append("stream")
        if caps.interruption:
            cap_list.append("interrupt")
        if caps.steering:
            cap_list.append("steer")
        if caps.image_input:
            cap_list.append("vision")
        if caps.local_tools:
            cap_list.append("tools")
        if caps.sandboxing:
            cap_list.append("sandbox")
        if caps.long_running_runtime:
            cap_list.append("long-run")
        caps_str = ", ".join(cap_list[:4])

        # Version string
        if name == "kratos_native":
            ver_str = "kratos-core 0.1.0"
        elif name == "codex":
            ver_str = f"openai {pkg_versions.get('openai', 'unknown')}"
        elif name == "claude":
            ver_str = f"anthropic {pkg_versions.get('anthropic', 'not installed')}"
        elif name == "gemini_live":
            ver_str = f"google-genai {pkg_versions.get('google.genai', 'unknown')}"
        elif name == "antigravity":
            ver_str = f"antigravity {pkg_versions.get('google.antigravity', 'disabled')}"
        else:
            ver_str = "external runtime"

        status_display = status_styles.get(health.status, str(health.status.value))
        if isinstance(health.details, dict):
            details_str = ", ".join(f"{k}: {v}" for k, v in health.details.items() if k not in ("error",) and v)
            if health.error:
                details_str += f" (Error: {health.error})"
        else:
            details_str = str(health.details or health.error or "Ready")

        if not cb.can_execute():
            details_str += f" [bold red](Circuit Breaker: {cb.state.value})[/bold red]"

        details = details_str

        table.add_row(
            name.upper() if name != "kratos_native" else "KRATOS NATIVE",
            status_display,
            ver_str,
            caps_str,
            details,
        )

    if console:
        console.print(table)
    return table


def inspect_provider(provider_name: str, console: Console | None = None) -> Panel | None:
    """Renders detailed capabilities, circuit breaker state, and telemetry for a provider."""
    registry = ProviderRegistry.get_instance()
    try:
        backend = registry.get(provider_name)
    except Exception as e:
        if console:
            console.print(f"[bold red]Provider '{provider_name}' not found:[/bold red] {e}")
        return None

    health = registry.health_check(provider_name)
    cb = registry.circuit_breaker(provider_name)
    caps = backend.capabilities()

    info_lines = [
        f"[bold gold1]Provider:[/bold gold1] {provider_name}",
        f"[bold gold1]Status:[/bold gold1] {health.status.value.upper()}",
        f"[bold gold1]Details:[/bold gold1] {health.details}",
        f"[bold gold1]Circuit Breaker:[/bold gold1] {cb.state.value} (consecutive failures: {cb.failure_count})",
        "",
        "[bold cyan]Capabilities:[/bold cyan]",
        f"  • Streaming: {caps.streaming}",
        f"  • Interruption: {caps.interruption}",
        f"  • Mid-turn Steering: {caps.steering}",
        f"  • Vision / Image Input: {caps.image_input}",
        f"  • Local Tool Execution: {caps.local_tools}",
        f"  • MCP Support: {caps.mcp}",
        f"  • Subagent Spawning: {caps.subagents}",
        f"  • Workspace Sandboxing: {caps.sandboxing}",
        f"  • Long-running Runtime: {caps.long_running_runtime}",
        f"  • Max Context Tokens: {caps.max_context_tokens:,}",
    ]

    panel = Panel(
        "\n".join(info_lines),
        title=f"[bold red]⚔️ PROVIDER INSPECTION: {provider_name.upper()}[/bold red]",
        border_style="gold1",
        padding=(1, 2),
    )

    if console:
        console.print(panel)
    return panel
