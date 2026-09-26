"""Contract tests verifying that all provider adapters conform to AgentBackend/ExecutionBackend."""

import pytest
from kratos_agent.providers.base import (
    AgentBackend,
    AgentCapabilities,
    AgentRun,
    AgentSession,
)
from kratos_agent.providers.claude.adapter import ClaudeAdapter
from kratos_agent.providers.codex.adapter import CodexAdapter
from kratos_agent.providers.deepseek.adapter import DeepSeekHarnessAdapter
from kratos_agent.providers.kimi.adapter import KimiAdapter
from kratos_agent.providers.kratos_native import KratosNativeBackend
from kratos_agent.providers.mock import MockProvider, StreamingProvider


@pytest.mark.parametrize(
    "adapter_cls, kwargs",
    [
        (MockProvider, {"name": "mock"}),
        (StreamingProvider, {"name": "streamer"}),
        (KratosNativeBackend, {}),
        (CodexAdapter, {}),
        (ClaudeAdapter, {}),
        (KimiAdapter, {}),
        (DeepSeekHarnessAdapter, {}),
    ],
)
def test_provider_contract_interface(adapter_cls, kwargs):
    """Every backend must conform to the AgentBackend protocol and expose valid capabilities."""
    backend = adapter_cls(**kwargs)

    assert isinstance(backend, AgentBackend)
    assert isinstance(backend.name, str) and len(backend.name) > 0

    caps = backend.capabilities()
    assert isinstance(caps, AgentCapabilities)
    assert isinstance(caps.streaming, bool)
    assert isinstance(caps.tool_calling, bool)
    assert isinstance(caps.session_persistence, bool)
