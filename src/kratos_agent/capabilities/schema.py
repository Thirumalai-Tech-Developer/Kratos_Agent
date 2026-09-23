from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(slots=True)
class CapabilitySpec:
    capability_id: str
    name: str
    description: str
    category: str
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    preconditions: List[str] = field(default_factory=list)
    postconditions: List[str] = field(default_factory=list)
    supported_backends: List[str] = field(default_factory=list)
    verifier: str | None = None
    retry_policy: Dict[str, Any] = field(default_factory=dict)
    timeout_policy: Dict[str, Any] = field(default_factory=dict)
    dangerous_level: str = "normal"
    availability: str = "unknown"
    version: str = "1"
    readiness_probe: str | None = None
    permissions: List[str] = field(default_factory=list)
