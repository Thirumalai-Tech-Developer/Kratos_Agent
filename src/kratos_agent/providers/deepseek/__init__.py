"""DeepSeek Harness adapter package for Kratos Agent.

Provides integration with DeepSeek Harness for long-running and execution-heavy tasks
using an isolated runtime environment (.kratos/providers/deepseek).
"""

from kratos_agent.providers.deepseek.adapter import DeepSeekHarnessAdapter
from kratos_agent.providers.deepseek.lifecycle import DeepSeekLifecycleManager
from kratos_agent.providers.deepseek.mapper import (
    extract_reasoning_and_content,
    map_deepseek_error,
    map_deepseek_event,
)

__all__ = [
    "DeepSeekHarnessAdapter",
    "DeepSeekLifecycleManager",
    "extract_reasoning_and_content",
    "map_deepseek_error",
    "map_deepseek_event",
]
