"""Google Antigravity SDK adapter package for Kratos Agent.

Provides integration with Google Antigravity Agent runtime behind feature flags
and capability probing.
"""

from kratos_agent.providers.antigravity.adapter import AntigravityAdapter
from kratos_agent.providers.antigravity.lifecycle import AntigravityLifecycleManager
from kratos_agent.providers.antigravity.mapper import (
    map_antigravity_error,
    map_antigravity_thought_event,
    map_antigravity_token_event,
    map_antigravity_tool_call,
)

__all__ = [
    "AntigravityAdapter",
    "AntigravityLifecycleManager",
    "map_antigravity_error",
    "map_antigravity_thought_event",
    "map_antigravity_token_event",
    "map_antigravity_tool_call",
]
