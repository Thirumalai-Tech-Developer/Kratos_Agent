from __future__ import annotations

import re
import traceback as tb
import uuid
from dataclasses import dataclass, field
from typing import Any

_SECRET_RE = re.compile(r"(AIza[0-9A-Za-z_-]{20,}|sk-[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._-]+)", re.IGNORECASE)


@dataclass(slots=True)
class ErrorEnvelope:
    error_id: str = field(default_factory=lambda: f"ERR-{uuid.uuid4().hex[:10].upper()}")
    task_id: str | None = None
    request_id: str | None = None
    component: str = "unknown"
    stage: str = "unknown"
    error_type: str = "RuntimeError"
    message: str = ""
    user_message: str = ""
    retryable: bool = False
    recovery_action: str | None = None
    traceback_reference: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_id": self.error_id,
            "task_id": self.task_id,
            "request_id": self.request_id,
            "component": self.component,
            "stage": self.stage,
            "error_type": self.error_type,
            "message": self.message,
            "user_message": self.user_message or self.message,
            "retryable": self.retryable,
            "recovery_action": self.recovery_action,
            "traceback_reference": self.traceback_reference,
            "evidence": self.evidence,
        }


def error_from_exception(
    exc: BaseException,
    *,
    component: str,
    stage: str,
    task_id: str | None = None,
    request_id: str | None = None,
    retryable: bool = False,
    recovery_action: str | None = None,
    user_message: str | None = None,
) -> ErrorEnvelope:
    message = _SECRET_RE.sub("[REDACTED]", str(exc) or type(exc).__name__).strip()
    return ErrorEnvelope(
        task_id=task_id,
        request_id=request_id,
        component=component,
        stage=stage,
        error_type=type(exc).__name__,
        message=message,
        user_message=user_message or message,
        retryable=retryable,
        recovery_action=recovery_action,
        traceback_reference=tb.format_exc(limit=20),
    )
