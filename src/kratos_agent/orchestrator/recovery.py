from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class RecoveryDecision:
    action: str
    reason: str
    retryable: bool = False


def classify_error(error: dict[str, Any] | None) -> str:
    text = str((error or {}).get("type") or (error or {}).get("message") or "").lower()
    for kind in ("transient", "authentication", "readiness", "target", "validation", "permission", "verification"):
        if kind in text:
            return kind
    return "execution"


def recover(error: dict[str, Any] | None, attempt: int) -> RecoveryDecision:
    category = classify_error(error)
    if category in {"transient", "readiness"} and attempt < 3:
        return RecoveryDecision("retry", f"{category} failure; retry with fresh observation", True)
    if category in {"target", "verification"} and attempt < 2:
        return RecoveryDecision("replan", f"{category} failure; switch grounding/backend", True)
    return RecoveryDecision("fail", f"non-recoverable {category} failure", False)
