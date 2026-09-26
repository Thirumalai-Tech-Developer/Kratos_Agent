from __future__ import annotations

from typing import Any

from .registry import get_capability_registry


def discover_capabilities(query: str, limit: int = 8) -> list[dict[str, Any]]:
    return [
        {
            "capability_id": spec.capability_id,
            "name": spec.name,
            "description": spec.description,
            "category": spec.category,
            "input_schema": spec.input_schema,
            "output_schema": spec.output_schema,
            "verifier": spec.verifier,
            "dangerous_level": spec.dangerous_level,
            "availability": spec.availability,
        }
        for spec in get_capability_registry().discover(query, limit=limit)
    ]
