"""Comprehensive tests for DeepSeek Harness architecture, Cordis kernel, and presets."""

import json
from pathlib import Path

from kratos_agent.core.harness import (
    HarnessKernel,
    HarnessPlugin,
    PluginMetadata,
    PluginState,
    HarnessPreset,
    StandardPreset,
    CodePreset,
    MinimalPreset,
    CreatorPreset,
    get_preset,
)
from kratos_agent.core.harness.plugins import (
    ToolsPlugin,
    MemoryPlugin,
    DeepSeekModelPlugin,
    AuditPlugin,
    CreatorPlugin,
)
from kratos_agent.main import KratosRuntime


class SampleDepPlugin(HarnessPlugin):
    def __init__(self):
        super().__init__(
            metadata=PluginMetadata(
                name="sample_dep",
                version="1.0.0",
                description="Dependency plugin",
            )
        )


class SampleConsumerPlugin(HarnessPlugin):
    def __init__(self):
        super().__init__(
            metadata=PluginMetadata(
                name="sample_consumer",
                version="1.0.0",
                description="Consumer plugin with dependency",
                dependencies=["sample_dep"],
            )
        )


def test_kernel_plugin_lifecycle_and_dependencies():
    kernel = HarnessKernel()
    dep = SampleDepPlugin()
    consumer = SampleConsumerPlugin()

    # Consumer cannot be enabled before dependency is registered/enabled
    kernel.register_plugin(consumer, enable_immediately=False)
    assert consumer.state == PluginState.LOADED
    assert not kernel.enable_plugin("sample_consumer")

    # Register and enable dependency
    kernel.register_plugin(dep, enable_immediately=True)
    assert dep.state == PluginState.ENABLED

    # Now consumer can be enabled
    assert kernel.enable_plugin("sample_consumer")
    assert consumer.state == PluginState.ENABLED

    # Disabling dependency should cascade disable consumer
    assert kernel.disable_plugin("sample_dep")
    assert dep.state == PluginState.DISABLED
    assert consumer.state == PluginState.DISABLED

    # Unregister plugin
    assert kernel.unregister_plugin("sample_consumer")
    assert kernel.get_plugin("sample_consumer") is None


def test_kernel_event_bus():
    kernel = HarnessKernel()
    received_events = []

    def on_custom_event(**kwargs):
        received_events.append(kwargs)

    unsub = kernel.on("test_event", on_custom_event)
    kernel.emit("test_event", message="hello harness", val=42)

    assert len(received_events) == 1
    assert received_events[0]["message"] == "hello harness"
    assert received_events[0]["val"] == 42

    # Unsubscribe and emit again
    unsub()
    kernel.emit("test_event", message="ignored")
    assert len(received_events) == 1


def test_signature_presets_and_tool_filtering():
    kernel = HarnessKernel()
    tools_plugin = ToolsPlugin()
    kernel.register_plugin(tools_plugin)

    # 1. Standard Preset: unrestricted tools
    kernel.apply_preset("standard")
    assert kernel.active_preset_name == "standard"
    assert tools_plugin.is_tool_allowed("read_file")
    assert tools_plugin.is_tool_allowed("any_custom_tool")

    # 2. Minimal Preset: bare-metal tools only
    kernel.apply_preset("minimal")
    assert kernel.active_preset_name == "minimal"
    assert tools_plugin.is_tool_allowed("read_file")
    assert tools_plugin.is_tool_allowed("write_file")
    assert tools_plugin.is_tool_allowed("run_terminal_command")
    assert not tools_plugin.is_tool_allowed("git_commit")
    assert not tools_plugin.is_tool_allowed("fetch_url")

    # 3. Code Preset: precision refactoring tools
    kernel.apply_preset("code")
    assert kernel.active_preset_name == "code"
    assert tools_plugin.is_tool_allowed("replace_file_content")
    assert tools_plugin.is_tool_allowed("multi_replace_file_content")
    assert tools_plugin.is_tool_allowed("read_file")
    assert tools_plugin.is_tool_allowed("git_status")
    assert not tools_plugin.is_tool_allowed("google_search")

    # Test filtering of tool definitions
    sample_defs = [
        {"name": "read_file", "description": "read"},
        {"name": "google_search", "description": "search"},
    ]
    filtered = tools_plugin.filter_tool_definitions(sample_defs)
    assert len(filtered) == 1
    assert filtered[0]["name"] == "read_file"


def test_deepseek_model_plugin_reasoning_and_dsml():
    model_plugin = DeepSeekModelPlugin()

    # 1. Reasoning token separation
    raw_response = (
        "<think>\n"
        "Need to inspect the repository structure first.\n"
        "Will invoke read_file to check package.json.\n"
        "</think>\n"
        "Here is the project overview."
    )
    reasoning, content = model_plugin.extract_reasoning_and_content(raw_response)
    assert "Need to inspect the repository structure" in reasoning
    assert "Here is the project overview." == content
    assert "<think>" not in content

    # 2. DSML parameter extraction
    dsml_response = (
        "<think>Let's run a test</think>\n"
        "<tool>{\"name\": \"run_terminal_command\", \"arguments\": {\"command\": \"pytest\"}}</｜｜DSML｜｜ parameter>\n"
        "</｜｜DSML｜｜ invoke>"
    )
    parsed = model_plugin.parse_model_output(dsml_response)
    assert "Let's run a test" in parsed["reasoning"]
    assert len(parsed["tool_calls"]) == 1
    assert parsed["tool_calls"][0]["name"] == "run_terminal_command"
    assert parsed["tool_calls"][0]["arguments"] == {"command": "pytest"}

    # 3. Standard <tool> tag extraction
    std_response = (
        "<tool>{\"name\": \"read_file\", \"arguments\": {\"file_path\": \"README.md\"}}</tool>"
    )
    tools = model_plugin.extract_dsml_tool_calls(std_response)
    assert len(tools) == 1
    assert tools[0]["name"] == "read_file"
    assert tools[0]["arguments"] == {"file_path": "README.md"}


def test_audit_plugin_trace_and_replay(tmp_path):
    log_dir = tmp_path / "trace"
    kernel = HarnessKernel()
    audit = AuditPlugin(config={"log_dir": str(log_dir)})
    kernel.register_plugin(audit)

    # Trigger events
    kernel.apply_preset("code")
    audit.record_event("custom_action", {"detail": "verification passed"})

    trace = audit.get_trace()
    assert len(trace) >= 2
    # Verify sequence numbering and timestamps
    assert trace[0]["seq"] == 1
    assert "timestamp" in trace[0]
    event_types = [e["event_type"] for e in trace]
    assert "preset_change" in event_types
    assert "custom_action" in event_types

    # Verify replay
    replay = audit.replay_session()
    assert len(replay) == len(trace)
    assert replay[0]["seq"] < replay[1]["seq"]

    # Verify export
    export_file = tmp_path / "exported_trace.json"
    exported_count = audit.export_trace(str(export_file))
    assert exported_count == len(trace)
    assert export_file.exists()


def test_creator_plugin_meta_programming():
    creator = CreatorPlugin()
    kernel = HarnessKernel()
    kernel.register_plugin(creator)

    # 1. Generate scaffold
    scaffold = creator.generate_plugin_scaffold("metrics_collector", description="Collects runtime metrics", category="audit")
    assert "class MetricsCollectorPlugin(HarnessPlugin):" in scaffold
    assert 'name="metrics_collector"' in scaffold

    # 2. Validate AST
    is_valid, err = creator.validate_plugin_code(scaffold)
    assert is_valid
    assert err is None

    # 3. Invalid syntax detection
    is_valid, err = creator.validate_plugin_code("def broken_code(:")
    assert not is_valid
    assert "Syntax error" in err

    # 4. Dynamic compilation and registration
    dyn_code = """
from kratos_agent.core.harness.plugin import HarnessPlugin, PluginMetadata

class DynamicTestPlugin(HarnessPlugin):
    def __init__(self):
        super().__init__(metadata=PluginMetadata(name="dynamic_test", version="1.0.0"))
        self.activated = False

    def on_enable(self):
        super().on_enable()
        self.activated = True
"""
    plugin, err = creator.load_plugin_from_source(dyn_code, "DynamicTestPlugin", enable=True)
    assert err is None
    assert plugin is not None
    assert plugin.name == "dynamic_test"
    assert plugin.state == PluginState.ENABLED
    assert plugin.activated is True
    assert kernel.get_plugin("dynamic_test") is not None


def test_runtime_harness_integration(tmp_path):
    runtime = KratosRuntime(workspace=tmp_path)
    assert hasattr(runtime, "harness")
    assert runtime.harness is not None

    # Status check
    status = runtime.get_harness_status()
    assert status["active_preset"] == "standard"
    assert "tools" in status["enabled_plugins"]
    assert "deepseek_model" in status["enabled_plugins"]
    assert "memory" in status["enabled_plugins"]
    assert "audit" in status["enabled_plugins"]
    assert "creator" in status["enabled_plugins"]

    # Preset switching to code mode
    preset = runtime.set_harness_mode("code")
    assert preset["name"] == "code"
    assert runtime.harness.active_preset_name == "code"

    # Test tool permission enforcement under code preset
    from kratos_agent.core.runtime_contracts import ToolSpec, ToolPermission

    allowed_spec = ToolSpec("read_file", "read file", {}, ToolPermission.READ)
    allowed, reason = runtime._allow_tool(allowed_spec, {"file_path": "test.txt"})
    assert allowed

    disallowed_spec = ToolSpec("fetch_url", "fetch url", {}, ToolPermission.READ)
    allowed, reason = runtime._allow_tool(disallowed_spec, {"url": "https://example.com"})
    assert not allowed
    assert "disabled under active harness preset 'code'" in reason

    # Reset back to standard
    runtime.set_harness_mode("standard")
    allowed, _ = runtime._allow_tool(disallowed_spec, {"url": "https://example.com"})
    assert allowed


def test_todo_write_tool_and_agent_loop_sync(tmp_path):
    from kratos_agent.utils.tools import todo_write
    from kratos_agent.core.task_manager import TaskState

    runtime = KratosRuntime(workspace=tmp_path)
    todos = [
        {"content": "Analyze dependencies", "status": "completed"},
        {"content": "Implement core logic", "status": "in_progress"},
        {"content": "Run test suite", "status": "pending"},
    ]

    res = todo_write(todos)
    assert "3 item(s)" in res
    assert "1 completed" in res
    assert "1 in_progress" in res
    assert "1 pending" in res

    # Verify AgentLoop task list sync
    assert runtime.loop.current_plan is not None
    assert len(runtime.loop.current_plan.tasks) == 3
    assert runtime.loop.current_plan.tasks[0].state == TaskState.COMPLETED
    assert runtime.loop.current_plan.tasks[1].state == TaskState.RUNNING
    assert runtime.loop.current_plan.tasks[2].state == TaskState.PENDING

    # Test JSON string parsing fallback
    json_todos = json.dumps([
        {"content": "Final step", "status": "pending"}
    ])
    res2 = todo_write(json_todos)
    assert "1 item(s)" in res2
    assert len(runtime.loop.current_plan.tasks) == 1


def test_exit_plan_mode_and_plan_guard(tmp_path):
    from kratos_agent.utils.tools import exit_plan_mode
    from kratos_agent.core.runtime_contracts import ToolSpec, ToolPermission

    runtime = KratosRuntime(workspace=tmp_path)

    # 1. Enter Plan Mode
    runtime.plan_mode = True
    assert runtime.plan_mode is True

    # 2. Check that mutations are prohibited in Plan Mode
    write_spec = ToolSpec("write_file", "write file", {}, ToolPermission.WRITE)
    allowed, reason = runtime._allow_tool(write_spec, {"file_path": "app.py"})
    assert not allowed
    assert "Plan Mode active" in reason

    cmd_spec = ToolSpec("run_terminal_command", "run command", {}, ToolPermission.EXECUTE)
    allowed, reason = runtime._allow_tool(cmd_spec, {"command": "npm install"})
    assert not allowed
    assert "Plan Mode active" in reason

    # 3. Check that exploration and plan tools are allowed in Plan Mode
    read_spec = ToolSpec("read_file", "read file", {}, ToolPermission.READ)
    allowed, _ = runtime._allow_tool(read_spec, {"file_path": "README.md"})
    assert allowed

    plan_tool_spec = ToolSpec("exit_plan_mode", "exit plan mode", {}, ToolPermission.READ)
    allowed, _ = runtime._allow_tool(plan_tool_spec, {"plan": "# Plan"})
    assert allowed

    todo_tool_spec = ToolSpec("todo_write", "todo write", {}, ToolPermission.READ)
    allowed, _ = runtime._allow_tool(todo_tool_spec, {"todos": []})
    assert allowed

    # 4. Exit Plan Mode via tool
    res = exit_plan_mode("# Architecture Specification\n\n1. Module A\n2. Module B")
    assert "Plan submitted successfully" in res
    assert runtime.plan_mode is False

    # 5. Mutations now unlocked
    allowed, _ = runtime._allow_tool(write_spec, {"file_path": "app.py"})
    assert allowed


def test_code_preset_includes_todo_and_plan_tools():
    assert "todo_write" in CodePreset.allowed_tools
    assert "exit_plan_mode" in CodePreset.allowed_tools

