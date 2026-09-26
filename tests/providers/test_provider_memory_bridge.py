"""Tests for Kratos memory authority and provider context bridge."""

import pytest
from kratos_agent.providers.context_bridge import ProviderContextBridge


def test_context_bridge_builds_layered_prompt():
    bridge = ProviderContextBridge(max_context_length=4000)

    system_prompt = bridge.build_system_context(
        provider_name="codex",
        user_instructions="Refactor database layer",
        workspace_summary="Active workspace: python 3.12, 12 files",
        memory_snippets=["Previously fixed connection pool leak", "Database uses asyncpg"],
        visual_summary="Error modal showing connection timeout",
    )

    assert "KRATOS SPECIALIST DIRECTIVE" in system_prompt
    assert "codex" in system_prompt
    assert "Refactor database layer" in system_prompt
    assert "Active workspace" in system_prompt
    assert "Previously fixed connection pool leak" in system_prompt
    assert "VISUAL CONTEXT" in system_prompt


def test_context_bridge_compaction():
    bridge = ProviderContextBridge(max_context_length=500)
    huge_memory = ["Memory note " + "x" * 100 for _ in range(10)]

    system_prompt = bridge.build_system_context(
        provider_name="claude",
        user_instructions="Short instruction",
        memory_snippets=huge_memory,
    )

    # Must fit within configured budget
    assert len(system_prompt) <= 600
    assert "Short instruction" in system_prompt
