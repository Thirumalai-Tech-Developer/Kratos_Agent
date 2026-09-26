"""Test fixtures and mock providers for Kratos multi-SDK test suite."""

import pytest
from pathlib import Path
from kratos_agent.providers.base import AgentCapabilities
from kratos_agent.providers.mock import (
    MockProvider,
    StreamingProvider,
    FailingProvider,
    InterruptibleProvider,
    SteerableProvider,
)
from kratos_agent.providers.registry import ProviderRegistry
from kratos_agent.providers.router import ProviderRouter


@pytest.fixture
def mock_registry():
    """Returns an isolated ProviderRegistry with mock specialists."""
    reg = ProviderRegistry()
    reg.register_provider(MockProvider(name="mock_fast", response_text="Fast response"))
    reg.register_provider(MockProvider(name="mock_reasoning", response_text="Reasoned response", capabilities=AgentCapabilities(reasoning=True)))
    reg.register_provider(StreamingProvider(name="mock_stream"))
    reg.register_provider(FailingProvider(name="mock_failing", fail_count=5))
    reg.register_provider(InterruptibleProvider(name="mock_interruptible"))
    reg.register_provider(SteerableProvider(name="mock_steerable"))
    return reg


@pytest.fixture
def mock_router(mock_registry, tmp_path):
    """Returns an isolated ProviderRouter using the mock registry."""
    return ProviderRouter(registry=mock_registry, workspace_root=tmp_path)
