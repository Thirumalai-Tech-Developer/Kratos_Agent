from pathlib import Path

from kratos_agent.core.agent_loop import AgentLoop, explicitly_requested_reusable_tool
from kratos_agent.core.context_pipeline import ContextBuilder
from kratos_agent.core.runtime_contracts import AgentRunState, ToolCall, ToolResult


class ToolSpy:
    def __init__(self):
        self.called = False

    def execute(self, call, allow):
        self.called = True
        return ToolResult(call.call_id, call.name, "created", is_error=False)


def make_loop(tmp_path: Path, user_request: str, tools: ToolSpy) -> AgentLoop:
    loop = AgentLoop(
        context=ContextBuilder(),
        instructions=object(),
        tools=tools,
        model=object(),
        emit=lambda event: None,
        workspace=tmp_path,
    )
    loop.current_run = AgentRunState("test", user_request, str(tmp_path))
    return loop


def test_reusable_tool_creation_requires_explicit_user_request():
    assert not explicitly_requested_reusable_tool("Create a coffee shop website")
    assert explicitly_requested_reusable_tool("Create a new reusable Kratos tool for weather")
    assert explicitly_requested_reusable_tool("Add a custom tool that formats SQL")


def test_one_off_website_task_cannot_mutate_kratos_tool_catalog(tmp_path):
    tools = ToolSpy()
    loop = make_loop(tmp_path, "Create a standalone website in this workspace", tools)

    result = loop._execute_tool_call_worker(
        ToolCall("self_tool_creator", {"tool_name": "write_website", "python_code": "..."}),
        lambda spec, args: (True, "allowed"),
    )

    assert result.is_error
    assert "Use existing workspace tools" in result.content
    assert not tools.called


def test_explicit_reusable_tool_request_can_use_tool_creator(tmp_path):
    tools = ToolSpy()
    loop = make_loop(tmp_path, "Create a new reusable Kratos tool for weather", tools)

    result = loop._execute_tool_call_worker(
        ToolCall("self_tool_creator", {"tool_name": "weather", "python_code": "..."}),
        lambda spec, args: (True, "allowed"),
    )

    assert not result.is_error
    assert tools.called


def test_identical_failed_shell_command_is_not_executed_twice(tmp_path):
    tools = ToolSpy()
    loop = make_loop(tmp_path, "Create a standalone website", tools)
    command = 'powershell -Command "Get-Content index.html | Select-Object -First 100"'
    loop.current_run.completed_tools.append({
        "name": "run_terminal_command",
        "args": {"command": command},
        "is_error": True,
    })

    result = loop._execute_tool_call_worker(
        ToolCall("run_terminal_command", {"command": command}),
        lambda spec, args: (True, "allowed"),
    )

    assert result.is_error
    assert "Repeated identical failed command blocked" in result.content
    assert not tools.called


def test_artifact_inspection_loop_is_bounded(tmp_path):
    tools = ToolSpy()
    loop = make_loop(tmp_path, "Create a website in this workspace", tools)
    loop.current_run.completed_tools.extend(
        {"name": "grep_search", "args": {"query": f"selector-{i}"}, "is_error": False}
        for i in range(12)
    )

    result = loop._execute_tool_call_worker(
        ToolCall("grep_search", {"query": "one-more-selector"}),
        lambda spec, args: (True, "allowed"),
    )

    assert result.is_error
    assert "Inspection loop limit reached" in result.content
    assert not tools.called
