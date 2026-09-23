from __future__ import annotations

from typing import Any, Dict

from .evidence import Evidence


class VerificationEngine:
    def verify(self, result: Dict[str, Any], expected_state: Dict[str, Any] | None = None) -> Evidence:
        expected = expected_state or {}
        evidence = dict(result.get("evidence") or result)
        verified = bool(result.get("verified", result.get("ok", False)))
        missing = [key for key, value in expected.items() if evidence.get(key) != value]
        if missing:
            verified = False
        return Evidence(
            verified=verified,
            summary="verified" if verified else f"missing or mismatched evidence: {', '.join(missing)}",
            data=evidence,
        )
