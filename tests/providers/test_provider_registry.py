"""Tests for ProviderRegistry, registration, and circuit breakers."""

import pytest
from kratos_agent.providers.base import ProviderUnavailable
from kratos_agent.providers.health import HealthStatus, CircuitState
from kratos_agent.providers.registry import ProviderRegistry
from kratos_agent.providers.mock import MockProvider


def test_registry_registration_and_lookup():
    reg = ProviderRegistry()
    mock = MockProvider(name="custom_worker")
    reg.register_provider(mock)

    assert reg.get("custom_worker") is mock
    assert reg.get_provider("custom_worker") is mock
    assert "custom_worker" in reg.list_providers()


def test_registry_unregistered_raises_unavailable():
    reg = ProviderRegistry()
    with pytest.raises(ProviderUnavailable):
        reg.get("non_existent_provider_xyz")


def test_registry_fallback_chain():
    reg = ProviderRegistry()
    reg.register_provider(MockProvider(name="p1"))
    reg.register_provider(MockProvider(name="p2"))
    reg.register_provider(MockProvider(name="p3"))
    reg.set_fallback_chain(["p1", "p2", "p3"])

    chain = reg.get_fallback_chain(primary_provider="p1")
    assert "p1" not in chain
    assert "p2" in chain
    assert "p3" in chain


def test_circuit_breaker_transition():
    reg = ProviderRegistry()
    cb = reg.circuit_breaker("flaky_service")
    assert cb.state == CircuitState.CLOSED
    assert cb.can_execute() is True

    # Record 3 failures (threshold)
    cb.record_failure("error 1")
    cb.record_failure("error 2")
    cb.record_failure("error 3")

    assert cb.state == CircuitState.OPEN
    assert cb.can_execute() is False

    # Reset
    cb.record_success()
    assert cb.state == CircuitState.CLOSED
    assert cb.can_execute() is True
