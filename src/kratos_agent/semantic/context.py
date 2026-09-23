from __future__ import annotations

from typing import Any, Dict


def build_semantic_context(
    *,
    current_request: str,
    screen_summary: str | None = None,
    active_application: str | None = None,
    active_browser: str | None = None,
    active_tab: str | None = None,
    task_state: Dict[str, Any] | None = None,
    recent_events: list[Dict[str, Any]] | None = None,
    memory: Dict[str, Any] | None = None,
    capabilities: list[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
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
