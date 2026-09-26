from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class CapabilitySpec:
    capability_id: str
    name: str
    description: str
    category: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    preconditions: list[str] = field(default_factory=list)
    postconditions: list[str] = field(default_factory=list)
    supported_backends: list[str] = field(default_factory=list)
    verifier: str | None = None
    retry_policy: dict[str, Any] = field(default_factory=dict)
    timeout_policy: dict[str, Any] = field(default_factory=dict)
    dangerous_level: str = "normal"
    availability: str = "unknown"
    version: str = "1"
    readiness_probe: str | None = None
    permissions: list[str] = field(default_factory=list)
