from __future__ import annotations

import json
from pathlib import Path

from ..core.runtime_contracts import ToolPermission, ToolSpec
from .manager import get_manager


def register_job_tools(registry, workspace: Path):
    def compact(status: dict) -> str:
        result = {key: value for key, value in status.items() if key not in ("profile", "jobs")}
        result["profile"] = {key: status["profile"].get(key) for key in ("name", "skills", "resume_name")}
        fields = ("id", "title", "company", "location", "score", "status", "eligible", "auto_apply_supported", "detail", "apply_url")
        result["jobs"] = [{key: job.get(key) for key in fields} for job in status["jobs"][:20]]
        return json.dumps(result)

    def jobs_status() -> str:
        """Read the applicant profile, job matches, blockers and submission receipts."""
        return compact(get_manager(workspace).status())

    def jobs_scan() -> str:
        """Scan free public sources for AI/ML roles using the saved profile and filters."""
        return compact(get_manager(workspace).command("scan"))

    def jobs_apply(job_id: str) -> str:
        """Queue one supported job application using only the applicant's saved resume and answers."""
        return compact(get_manager(workspace).command("apply", job_id))

    def jobs_autopilot(action: str) -> str:
        """Start or stop recurring job discovery and automatic applications. Never invent applicant facts."""
        if action not in ("start", "stop"):
            raise ValueError("action must be start or stop")
        return compact(get_manager(workspace).command(action))

    for name, handler, permission, properties in (
        ("jobs_status", jobs_status, ToolPermission.READ, {}),
        ("jobs_scan", jobs_scan, ToolPermission.NETWORK, {}),
        ("jobs_apply", jobs_apply, ToolPermission.NETWORK, {"job_id": {"type": "string"}}),
        ("jobs_autopilot", jobs_autopilot, ToolPermission.NETWORK, {"action": {"type": "string", "enum": ["start", "stop"]}}),
    ):
        registry.register(ToolSpec(name=name, description=handler.__doc__, permission=permission, source="builtin",
                                  parameters={"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}), handler)
