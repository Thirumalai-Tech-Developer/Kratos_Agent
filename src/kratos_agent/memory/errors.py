"""Error and recovery memory store for self-healing execution."""
from __future__ import annotations

from kratos_agent.memory.models import ErrorRecoveryRecord


class ErrorMemoryStore:
    """Stores known error patterns and proven recovery solutions (§26)."""

    def __init__(self) -> None:
        self._solutions: dict[str, ErrorRecoveryRecord] = {}

    def record_solution(self, error: str, solution: str, context: str = "") -> ErrorRecoveryRecord:
        key = error.strip().lower()
        if key in self._solutions:
            rec = self._solutions[key]
            rec.solution = solution
            rec.success_count += 1
            rec.confidence = min(1.0, rec.confidence + 0.05)
            return rec

        rec = ErrorRecoveryRecord(
            error=error,
            solution=solution,
            context=context,
        )
        self._solutions[key] = rec
        return rec

    def find_solution(self, error: str) -> ErrorRecoveryRecord | None:
        clean = error.strip().lower()
        if clean in self._solutions:
            return self._solutions[clean]

        for rec in self._solutions.values():
            if rec.error.lower() in clean or clean in rec.error.lower():
                return rec
        return None
