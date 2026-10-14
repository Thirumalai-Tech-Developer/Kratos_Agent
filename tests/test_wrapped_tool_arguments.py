from kratos_agent.core.runtime_contracts import ToolCall, ToolPermission, ToolSpec
from kratos_agent.core.tool_runtime import ToolRegistry
from kratos_agent.core.agent_loop import AgentLoop
from types import SimpleNamespace
from threading import Event


def test_wrapped_command_is_normalized_before_validation_and_approval():
    registry = ToolRegistry()
    registry.register(ToolSpec("run_terminal_command", "execute", {"properties": {"command": {"type": "string"}}, "required": ["command"], "additionalProperties": False}, ToolPermission.EXECUTE), lambda command: command)
    observed = []
    def deny(spec, arguments):
        observed.append(arguments.copy())
        return False, "approval required"
    result = registry.execute(ToolCall("run_terminal_command", {"arguments": {"cmd": "echo hello"}}), deny)
    assert observed == [{"command": "echo hello"}]
    assert result.is_error
    result = registry.execute(ToolCall("run_terminal_command", {"arguments": {"command": "echo hello"}}), lambda spec, args: (True, ""))
    assert not result.is_error
    assert "echo hello" in result.content


def test_declared_arguments_parameter_is_preserved():
    registry = ToolRegistry()
    registry.register(ToolSpec("custom", "custom", {"properties": {"arguments": {"type": "object"}}, "required": ["arguments"]}, ToolPermission.READ), lambda arguments: arguments["value"])
    result = registry.execute(ToolCall("custom", {"arguments": {"value": "preserved"}}), lambda spec, args: (True, ""))
    assert not result.is_error
    assert "preserved" in result.content


def test_failure_guard_compares_actual_wrapped_commands_not_empty_envelopes():
    registry = ToolRegistry()
    registry.register(ToolSpec("run_terminal_command", "execute", {"properties": {"command": {"type": "string"}}, "required": ["command"]}, ToolPermission.EXECUTE), lambda command: command)
    loop = AgentLoop.__new__(AgentLoop)
    loop.cancellation_flag = Event()
    loop.tools = registry
    loop.context = SimpleNamespace(prune_tool_result=lambda text: (text, False))
    loop.current_run = SimpleNamespace(completed_tools=[{"name": "run_terminal_command", "is_error": True, "args": {}}])
    call = ToolCall("run_terminal_command", {"arguments": {"command": "echo corrected"}})
    result = loop._execute_tool_call_worker(call, lambda spec, args: (True, ""))
    assert not result.is_error
    loop.current_run.completed_tools = [{"name": "run_terminal_command", "is_error": True, "args": {"command": "echo corrected"}}]
    call = ToolCall("run_terminal_command", {"arguments": {"cmd": "echo corrected"}})
    result = loop._execute_tool_call_worker(call, lambda spec, args: (True, ""))
    assert result.is_error
    assert "Repeated identical" in result.content


def test_provider_nonce_does_not_reach_handler_or_approval():
    registry = ToolRegistry()
    registry.register(ToolSpec("run_terminal_command", "execute", {"properties": {"command": {"type": "string"}}, "required": ["command"]}, ToolPermission.EXECUTE), lambda command: command)
    observed = []
    def allow(spec, args):
        observed.append(args.copy())
        return True, ""
    result = registry.execute(ToolCall("run_terminal_command", {"command": "date", "_nonce": "bketmnfc"}), allow)
    assert not result.is_error
    assert observed == [{"command": "date"}]
