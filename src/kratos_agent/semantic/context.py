from __future__ import annotations

from typing import Any


def build_semantic_context(
    *,
    current_request: str,
    screen_summary: str | None = None,
    active_application: str | None = None,
    active_browser: str | None = None,
    active_tab: str | None = None,
    task_state: dict[str, Any] | None = None,
    recent_events: list[dict[str, Any]] | None = None,
    memory: dict[str, Any] | None = None,
    capabilities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "current_request": current_request,
        "current_screen_summary": screen_summary,
        "active_application": active_application,
        "active_browser": active_browser,
        "active_tab": active_tab,
        "task_state": task_state or {},
        "recent_execution_events": recent_events or [],
        "relevant_memory": memory or {},
        "capability_candidates": capabilities or [],
    }
