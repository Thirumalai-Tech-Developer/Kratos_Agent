"""Structured error representation and context preservation for Kratos Agent (§2, §3, §4)."""
from __future__ import annotations

import sys
import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class KratosError:
    """Standard structured error preserving full diagnostic context across subsystems."""
    subsystem: str
    operation: str
    error_type: str
    message: str
    recoverable: bool = False
    retryable: bool = False
    details: Dict[str, Any] = field(default_factory=dict)
    cause: Optional[str] = None
    traceback: Optional[str] = None
    task_id: Optional[str] = None
    operation_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subsystem": self.subsystem,
            "operation": self.operation,
            "error_type": self.error_type,
            "message": self.message,
            "recoverable": self.recoverable,
            "retryable": self.retryable,
            "details": self.details,
            "cause": self.cause,
            "traceback": self.traceback,
            "task_id": self.task_id,
            "operation_id": self.operation_id,
        }

    def format_diagnostic(self) -> str:
        """Returns a clear, actionable diagnostic string for logs or debug views."""
        lines = [
            f"[{self.subsystem.upper()}:{self.operation}] {self.error_type}: {self.message}",
        ]
        if self.task_id:
            lines.append(f"  Task ID: {self.task_id}")
        if self.details:
            for k, v in self.details.items():
                lines.append(f"  {k}: {v}")
        if self.cause:
            lines.append(f"  Cause: {self.cause}")
        return "\n".join(lines)


def create_kratos_error(
    exc: Exception | str,
    subsystem: str,
    operation: str,
    task_id: Optional[str] = None,
    operation_id: Optional[str] = None,
    recoverable: bool = False,
    retryable: bool = False,
    details: Optional[Dict[str, Any]] = None,
) -> KratosError:
    """Creates a KratosError from an exception or error message without discarding context."""
    if isinstance(exc, Exception):
        err_type = type(exc).__name__
        err_msg = str(exc) or repr(exc)
        tb = traceback.format_exc()
        if tb.strip() == "NoneType: None":
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)) if exc.__traceback__ else None
        cause = str(exc.__cause__) if exc.__cause__ else None
    else:
        err_type = "KratosException"
        err_msg = str(exc)
        tb = None
        cause = None

    return KratosError(
        subsystem=subsystem,
        operation=operation,
        error_type=err_type,
        message=err_msg,
        recoverable=recoverable,
        retryable=retryable,
        details=details or {},
        cause=cause,
        traceback=tb,
        task_id=task_id,
        operation_id=operation_id,
    )


@dataclass
class TaskResult:
    """Standardized task result contract across subsystems (§44)."""
    task_id: str
    success: bool
    verified: bool
    subsystem: str
    operation: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    error: Optional[KratosError] = None
    recovery_attempts: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "success": self.success,
            "verified": self.verified,
            "subsystem": self.subsystem,
            "operation": self.operation,
            "evidence": self.evidence,
            "error": self.error.to_dict() if self.error else None,
            "recovery_attempts": self.recovery_attempts,
        }

