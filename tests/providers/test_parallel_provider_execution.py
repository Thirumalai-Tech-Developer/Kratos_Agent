"""Tests for safe parallel provider execution and resource conflict handling."""

import pytest
from kratos_agent.providers.mock import MockProvider
from kratos_agent.providers.registry import ProviderRegistry
from kratos_agent.providers.router import ProviderRouter
from kratos_agent.providers.base import AgentRun


@pytest.mark.asyncio
async def test_parallel_independent_tasks_execution(tmp_path):
    reg = ProviderRegistry()
    reg.register_provider(MockProvider(name="mock_doc_reader", response_text="Docs analyzed"))
    reg.register_provider(MockProvider(name="mock_test_checker", response_text="Tests inspected"))

    router = ProviderRouter(registry=reg, workspace_root=tmp_path)

    tasks = [
        {
            "task_id": "par-task-1",
            "prompt": "Analyze documentation",
            "provider": "mock_doc_reader",
            "reads": ["docs/README.md"],
        },
        {
            "task_id": "par-task-2",
            "prompt": "Check test coverage",
            "provider": "mock_test_checker",
            "reads": ["tests/test_auth.py"],
        },
    ]

    results = await router.execute_parallel(tasks, session_id="parallel-session-1")

    assert len(results) == 2
    assert all(isinstance(r, AgentRun) for r in results)
    assert results[0].output == "Docs analyzed"
    assert results[1].output == "Tests inspected"
