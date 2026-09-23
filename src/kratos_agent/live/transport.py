from __future__ import annotations

from typing import Any, Dict


def tool_result_payload(status: str, *, task_id: str | None = None, **payload: Any) -> Dict[str, Any]:
    result = {"status": status, **payload}
    if task_id:
        result["task_id"] = task_id
    return result
