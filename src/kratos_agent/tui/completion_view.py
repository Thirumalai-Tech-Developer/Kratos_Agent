"""Completion View: renders the polished final completion/result card for Kratos Agent.

Displays verified results, completed tasks count, changed files list, build/test status,
and next-step prompt readiness with strict truthfulness.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text


def render_completion_card(
    summary_text: str,
    plan_dict: Optional[Dict[str, Any]] = None,
    files_summary: Optional[Dict[str, Any]] = None,
    verification: Optional[Dict[str, Any]] = None,
    model_name: str = "",
) -> Panel:
    """Renders the truthful completion or failure panel."""
    elements = []

    # Determine True Success State
    is_success = True
    total_tasks = 0
    completed_tasks = 0
    unfinished_tasks = []

    if plan_dict:
        total_tasks = plan_dict.get("total_count", 0)
        completed_tasks = plan_dict.get("completed_count", 0)
        plan_state = plan_dict.get("state", "idle")
        tasks_list = plan_dict.get("tasks", [])
        unfinished_tasks = [t for t in tasks_list if t.get("state") not in ("completed", "skipped")]

        if plan_state != "completed" or (total_tasks > 0 and completed_tasks < total_tasks):
            is_success = False

    if verification:
        verif_passed = verification.get("passed", True)
        if not verif_passed:
            is_success = False

    # Title header
    header = Text()
    if is_success:
        header.append("✓ TASK COMPLETED", style="bold green")
    else:
        header.append("✗ TASK INCOMPLETE / FAILED", style="bold red")
    elements.append(header)
    elements.append(Text(""))

    # Concise user-facing summary message
    clean_summary = summary_text.strip()
    if clean_summary:
        summary_lines = [l for l in clean_summary.splitlines() if l.strip()]
        preview = summary_lines[0] if len(summary_lines) == 1 else "\n".join(summary_lines[:4])
        elements.append(Text(preview, style="white"))
        elements.append(Text(""))

    # Execution stats
    stats = []
    if total_tasks > 0:
        if completed_tasks == total_tasks:
            stats.append(f"✓ {completed_tasks}/{total_tasks} tasks completed")
        else:
            stats.append(f"✗ {completed_tasks}/{total_tasks} tasks completed ({len(unfinished_tasks)} remaining)")

    if files_summary:
        created = files_summary.get("created", [])
        modified = files_summary.get("modified", [])
        total_files = len(created) + len(modified)
        if total_files > 0:
            stats.append(f"✓ {total_files} file(s) created/modified")

    if verification:
        passed = verification.get("passed", True)
        files_checked = verification.get("files_checked", 0)
        details = verification.get("details", [])
        if passed and files_checked > 0:
            stats.append(f"✓ Workspace verified ({files_checked} files checked)")
        elif not passed:
            err_details = [d for d in details if "error" in d.lower() or "missing" in d.lower() or "no files" in d.lower()]
            err_msg = f": {err_details[0]}" if err_details else ""
            stats.append(f"✗ Verification failed{err_msg}")

    if stats:
        for stat in stats:
            elements.append(Text(stat, style="bold green" if "✓" in stat else "bold red"))
        elements.append(Text(""))

    # Unfinished tasks listing if any
    if unfinished_tasks:
        elements.append(Text("Unfinished Tasks:", style="bold yellow"))
        for ut in unfinished_tasks[:5]:
            elements.append(Text(f" • [{ut.get('state', 'pending').upper()}] {ut.get('title', 'Task')}", style="dim yellow"))
        elements.append(Text(""))

    # Changed files listing
    if files_summary:
        created = files_summary.get("created", [])
        modified = files_summary.get("modified", [])
        all_files = created + [f"{m} (modified)" for m in modified]
        if all_files:
            elements.append(Text("Files Created / Modified:", style="bold #D4AF37"))
            for f in all_files[:8]:
                elements.append(Text(f" • {f}", style="dim white"))
            if len(all_files) > 8:
                elements.append(Text(f" • ... and {len(all_files) - 8} more files", style="dim"))
            elements.append(Text(""))

    # Ready prompt
    elements.append(Text("Ready for your next request.", style="italic cyan"))

    model_badge = f" ({model_name})" if model_name else ""
    return Panel(
        Group(*elements),
        title=f"[bold red]⚔️  KRATOS[/bold red]{model_badge}",
        title_align="left",
        border_style="green" if is_success else "red",
        padding=(1, 2),
    )
