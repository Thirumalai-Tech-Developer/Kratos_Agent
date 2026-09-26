"""Tests for ToolAdapter schema translations (OpenAI, Claude, MCP) and traceability."""

import pytest
from kratos_agent.providers.tool_adapter import ToolAdapter
from kratos_agent.core.tool_runtime import ToolRegistry


def test_tool_adapter_schema_translations():
    reg = ToolRegistry()
    adapter = ToolAdapter(registry=reg)

    # 1. OpenAI schema translation
    openai_tools = adapter.to_openai_tools()
    assert isinstance(openai_tools, list)
    if openai_tools:
        first = openai_tools[0]
        assert first.get("type") == "function"
        assert "parameters" in first.get("function", {})

    # 2. Claude schema translation
    claude_tools = adapter.to_claude_tools()
    assert isinstance(claude_tools, list)
    if claude_tools:
        first_c = claude_tools[0]
        assert "name" in first_c
        assert "input_schema" in first_c

    # 3. MCP tools schema translation
    mcp_tools = adapter.to_mcp_tools()
    assert isinstance(mcp_tools, list)
    if mcp_tools:
        first_m = mcp_tools[0]
        assert first_m["name"].startswith("mcp__kratos__")


@pytest.mark.asyncio
async def test_tool_execution_traceability():
    reg = ToolRegistry()
    adapter = ToolAdapter(registry=reg)

    res, rec = await adapter.execute_tool(
        tool_name="list_dir",
        arguments={"path": "."},
        session_id="sess-trace-1",
        task_id="task-trace-1",
        provider="codex",
    )

    assert rec.session_id == "sess-trace-1"
    assert rec.task_id == "task-trace-1"
    assert rec.provider == "codex"
    assert rec.input_hash is not None
    assert rec.result_hash is not None
    assert rec.duration_ms >= 0.0
    assert len(adapter.get_execution_history()) > 0
