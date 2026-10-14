"""Real child activity stays scoped when the parent and siblings share a bus."""
import ast
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from kratos_agent.core.agent_loop import AgentLoop
from kratos_agent.core.context_pipeline import ContextBuilder
from kratos_agent.core.event_bus import event_bus
from kratos_agent.core.instruction_engine import InstructionEngine, InstructionModule
from kratos_agent.core.runtime_contracts import (
    AgentRunState, ChatMessage, EventKind, ModelResponse, RuntimeEvent, ToolCall, ToolPermission, ToolSpec,
)
from kratos_agent.core.subagents import SubagentManager, scoped_subagent_event
from kratos_agent.core.task_manager import ExecutionPlan, TaskItem, TaskState
from kratos_agent.core.tool_runtime import ToolRegistry
from kratos_agent.core.workspace_tracker import WorkspaceTracker


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    # Compile the composition methods without main.py's configured global
    # runtime, which would open the user's real provider and MCP connections.
    source = Path(__file__).parents[1] / "src/kratos_agent/main.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    klass = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "KratosRuntime")
    klass.body = [node for node in klass.body if isinstance(node, ast.FunctionDef)
                  and node.name in {"_run_isolated", "_check_tool_permission"}]
    namespace = {"Any": object, "ChatMessage": ChatMessage, "AgentLoop": AgentLoop,
                 "RuntimeEvent": RuntimeEvent, "EventKind": EventKind, "event_bus": event_bus,
                 "InstructionEngine": InstructionEngine, "InstructionModule": InstructionModule,
                 "ContextBuilder": ContextBuilder, "ToolPermission": ToolPermission,
                 "threading": threading,
                 "logger": logging.getLogger(__name__),
                 "prompt_library": SimpleNamespace(get_subagent_prompt=lambda role: f"Specialized {role} instructions."),
                 "assess_tool_risk": lambda *args: None,
                 "approval_gate": SimpleNamespace(mode="read"),
                 "ApprovalMode": SimpleNamespace(SOVEREIGN="sovereign", SUGGEST="suggest")}
    exec(compile(ast.Module(body=[klass], type_ignores=[]), str(source), "exec"), namespace)
    instance = namespace["KratosRuntime"]()
    instance.workspace = tmp_path
    instance.context = ContextBuilder()
    instance.context.provider_input_tokens = 1234
    instance.instructions = InstructionEngine()
    instance.instructions.register(InstructionModule("project", "project", lambda: "Project instructions."))
    instance.tools_registry = ToolRegistry()
    instance._cancellation_flag = threading.Event()
    instance.loop = SimpleNamespace(_current_turn_id="parent-turn", workspace_tracker=WorkspaceTracker(tmp_path),
        current_run=AgentRunState("parent-run", "Complete the project", tmp_path),
        current_plan=ExecutionPlan("Complete the project", tasks=[TaskItem("parent", "Implement and verify", TaskState.RUNNING)]))
    instance.persisted = []
    instance._emit = instance.persisted.append
    instance._allow_tool = lambda *args: (True, "allowed")
    instance.subagents = SubagentManager(instance._run_isolated)
    monkeypatch.setattr("kratos_agent.core.agent_loop.formulate_agent_plan", lambda **kwargs: None)
    return instance


class ScriptedModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def complete(self, request, on_chunk=None):
        self.requests.append(request)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        if on_chunk:
            on_chunk("Child response belongs only to this worker.")
        return response


def test_child_report_and_tools_publish_once_without_parent_tokens_or_usage(runtime):
    executed = []
    runtime.tools_registry.register(
        ToolSpec("read_file", "Read file", {"type": "object", "properties": {"file_path": {"type": "string"}},
                                            "required": ["file_path"]}, ToolPermission.READ),
        lambda file_path: executed.append(file_path) or "verified evidence",
    )
    runtime.model = ScriptedModel([
        ModelResponse(tool_calls=[ToolCall("read_file", {"file_path": "README.md"}, "read-1")]),
        ModelResponse(text="## Findings\nVerified the README."),
    ])
    published = []
    event_bus.subscribe(published.append)
    try:
        result = runtime.subagents.run("researcher", "Inspect README.md")
    finally:
        event_bus.unsubscribe(published.append)

    assert executed == ["README.md"]
    assert result.summary == "## Findings\nVerified the README."
    assert runtime.context.provider_input_tokens == 1234
    assert len(published) == len(runtime.persisted)
    assert all(event.kind.value.startswith("subagent.") for event in published)
    assert all(event.turn_id == "parent-turn" for event in published)
    assert all(event.payload["subagent"]["agent_id"] == result.agent_id for event in published)
    assert not any(event.payload.get("activity", {}).get("kind") == "model.chunk" for event in published)
    assert len([event for event in published if event.kind == EventKind.SUBAGENT_STARTED]) == 1
    final = published[-1]
    assert final.kind == EventKind.SUBAGENT_COMPLETED
    assert final.payload["subagent"]["status"] == "completed"
    assert final.payload["result"] == result.summary
    assert final.payload["duration_ms"] >= 0
    assert any(section["name"] == "subagent_role" for section in runtime.model.requests[0]["instructions"])


def test_child_todo_does_not_rebind_or_mutate_parent_handlers(runtime, monkeypatch):
    from kratos_agent.utils import tools as legacy_tools

    called = []
    parent_handler = lambda todos: called.append(todos)
    monkeypatch.setattr(legacy_tools, "_todo_handler", parent_handler)
    parent_plan_handler = lambda plan: called.append(plan)
    monkeypatch.setattr(legacy_tools, "_plan_mode_handler", parent_plan_handler)
    runtime.tools_registry.register(
        ToolSpec("todo_write", "Update tasks", {"type": "object", "properties": {"todos": {"type": "array"}},
                                               "required": ["todos"]}, ToolPermission.READ),
        parent_handler,
    )
    runtime.model = ScriptedModel([
        ModelResponse(tool_calls=[ToolCall("todo_write", {"todos": []}, "todo-1")]),
        ModelResponse(text="Child report complete."),
    ])
    result = runtime.subagents.run("tester", "Review the task list")
    assert result.error is None
    assert called == []
    assert runtime.tools_registry.get("todo_write").handler is parent_handler
    assert legacy_tools._todo_handler is parent_handler
    assert legacy_tools._plan_mode_handler is parent_plan_handler
    plans = [event for event in runtime.persisted if event.payload.get("activity", {}).get("kind") == "plan.created"]
    assert len(plans) == 1 and plans[0].payload["subagent"]["agent_id"] == result.agent_id


def test_actual_child_reads_writes_edits_and_commands_merge_into_parent_evidence(runtime):
    source = runtime.workspace / "README.md"
    source.write_text("Actual source evidence", encoding="utf-8")
    output = runtime.workspace / "report.md"
    executed = []
    runtime.tools_registry.register(
        ToolSpec("read_file", "Read file", {"type": "object", "properties": {"file_path": {"type": "string"}},
                                            "required": ["file_path"]}, ToolPermission.READ),
        lambda file_path: (runtime.workspace / file_path).read_text(encoding="utf-8"),
    )
    runtime.tools_registry.register(
        ToolSpec("write_file", "Write file", {"type": "object", "properties": {
            "file_path": {"type": "string"}, "content": {"type": "string"}}, "required": ["file_path", "content"]}, ToolPermission.WRITE),
        lambda file_path, content: (runtime.workspace / file_path).write_text(content, encoding="utf-8") or "Saved",
    )
    runtime.tools_registry.register(
        ToolSpec("edit_file", "Edit file", {"type": "object", "properties": {
            "file_path": {"type": "string"}, "content": {"type": "string"}}, "required": ["file_path", "content"]}, ToolPermission.WRITE),
        lambda file_path, content: (runtime.workspace / file_path).write_text(content, encoding="utf-8") or "Edited",
    )
    runtime.tools_registry.register(
        ToolSpec("run_terminal_command", "Run check", {"type": "object", "properties": {"command": {"type": "string"}},
                                                       "required": ["command"]}, ToolPermission.EXECUTE),
        lambda command: executed.append(command) or "OUTPUT: checked\nExit Code: 0",
    )
    runtime.model = ScriptedModel([
        ModelResponse(tool_calls=[ToolCall("read_file", {"file_path": "README.md"}, "actual-read")]),
        ModelResponse(tool_calls=[ToolCall("write_file", {"file_path": "report.md", "content": "Observed source"}, "actual-write")]),
        ModelResponse(tool_calls=[ToolCall("edit_file", {"file_path": "report.md", "content": "Verified source"}, "actual-edit")]),
        ModelResponse(tool_calls=[ToolCall("run_terminal_command", {"command": "verify report"}, "actual-command")]),
        ModelResponse(text="Verified delegated file work."),
    ])
    published = []
    event_bus.subscribe(published.append)
    try:
        result = runtime.subagents.run("researcher", "Inspect the source and prepare its report")
    finally:
        event_bus.unsubscribe(published.append)
    assert output.read_text(encoding="utf-8") == "Verified source"
    assert executed == ["verify report"]
    assert runtime.loop.workspace_tracker.all_changed_files == ["report.md"]
    assert runtime.loop.workspace_tracker.inspected_files == {"README.md"}
    assert runtime.loop.workspace_tracker.executed_commands[0]["command"] == "verify report"
    assert runtime.loop.current_run.written_files == ["report.md"]
    assert runtime.loop.current_run.inspected_files == ["README.md"]
    assert runtime.loop.current_run.commands_run == ["verify report"]
    assert [call["name"] for call in runtime.loop.current_run.completed_tools] == ["read_file", "write_file", "edit_file", "run_terminal_command"]
    assert all(call["subagent_id"] == result.agent_id for call in runtime.loop.current_run.completed_tools)
    assert runtime.loop.current_plan.tasks[0].state == TaskState.RUNNING
    assert len(published) == len(runtime.persisted)
    assert all(event.kind.value.startswith("subagent.") for event in published)


def test_failed_child_report_preserves_real_edits_without_completing_parent(runtime):
    runtime.tools_registry.register(
        ToolSpec("write_file", "Write file", {"type": "object", "properties": {
            "file_path": {"type": "string"}, "content": {"type": "string"}}, "required": ["file_path", "content"]}, ToolPermission.WRITE),
        lambda file_path, content: (runtime.workspace / file_path).write_text(content, encoding="utf-8") or "Saved",
    )
    runtime.model = ScriptedModel([
        ModelResponse(tool_calls=[ToolCall("write_file", {"file_path": "partial.md", "content": "Saved before failure"}, "partial-write")]),
        RuntimeError("Provider failed before the report"),
    ])
    result = runtime.subagents.run("researcher", "Prepare a report")
    assert "Model request failed:" in result.summary
    assert runtime.persisted[-1].kind == EventKind.SUBAGENT_FAILED
    assert runtime.loop.workspace_tracker.all_changed_files == ["partial.md"]
    assert runtime.loop.current_run.written_files == ["partial.md"]
    assert runtime.loop.current_plan.tasks[0].state == TaskState.RUNNING
    assert runtime.loop.current_run.status == "running"
    assert not any(event.kind == EventKind.TASK_COMPLETED for event in runtime.persisted)


def test_child_report_prose_cannot_create_parent_file_or_completion_evidence(runtime):
    runtime.model = ScriptedModel([ModelResponse(text="Created fake.md and completed every parent task.")])
    runtime.subagents.run("researcher", "Describe the workspace")
    assert runtime.loop.workspace_tracker.all_changed_files == []
    assert runtime.loop.current_run.written_files == []
    assert runtime.loop.current_run.completed_tools == []
    assert runtime.loop.current_plan.tasks[0].state == TaskState.RUNNING


def test_parallel_child_writes_merge_all_real_paths_and_keep_evidence_scoped(runtime):
    from kratos_agent.sdk.client import _request_context

    runtime.tools_registry.register(
        ToolSpec("write_file", "Write file", {"type": "object", "properties": {
            "file_path": {"type": "string"}, "content": {"type": "string"}}, "required": ["file_path", "content"]}, ToolPermission.WRITE),
        lambda file_path, content: (runtime.workspace / file_path).write_text(content, encoding="utf-8") or "Saved",
    )
    reached_model = threading.Barrier(2)
    seen = set()
    lock = threading.Lock()

    class ParallelWriteModel:
        def complete(self, request, on_chunk=None):
            agent_id = _request_context.get()["x-kratos-task-id"]
            with lock:
                first = agent_id not in seen
                seen.add(agent_id)
            if first:
                reached_model.wait(timeout=5)
                return ModelResponse(tool_calls=[ToolCall("write_file", {
                    "file_path": agent_id + ".md", "content": "Actual child output"}, agent_id + "-write")])
            return ModelResponse(text="Delegated file saved.")

    runtime.model = ParallelWriteModel()
    results = runtime.subagents.run_multi_parallel([{"role": "tester", "task": "Prepare output"}] * 2)
    paths = sorted(result.agent_id + ".md" for result in results)
    assert runtime.loop.workspace_tracker.all_changed_files == paths
    assert sorted(runtime.loop.current_run.written_files) == paths
    assert all((runtime.workspace / path).read_text(encoding="utf-8") == "Actual child output" for path in paths)
    evidence = runtime.loop.current_run.completed_tools
    assert len(evidence) == 2
    assert {item["subagent_id"] for item in evidence} == {result.agent_id for result in results}
    assert all(item["args"]["file_path"] == item["subagent_id"] + ".md" for item in evidence)
    assert runtime.loop.current_plan.tasks[0].state == TaskState.RUNNING


def test_returned_model_failure_has_failed_child_status(runtime):
    runtime.model = ScriptedModel([RuntimeError("Provider unavailable")])
    result = runtime.subagents.run("debugger", "Check error")
    assert "Model request failed:" in result.summary
    assert runtime.persisted[-1].kind == EventKind.SUBAGENT_FAILED
    assert runtime.persisted[-1].payload["subagent"]["status"] == "failed"
    assert "Provider unavailable" in runtime.persisted[-1].payload["error"]
    assert not any(event.kind == EventKind.SUBAGENT_COMPLETED for event in runtime.persisted)


def test_child_plan_submission_is_scoped_without_exiting_parent_plan_mode(runtime, monkeypatch):
    from kratos_agent.utils import tools as legacy_tools

    parent_plans = []
    parent_handler = parent_plans.append
    monkeypatch.setattr(legacy_tools, "_plan_mode_handler", parent_handler)
    runtime.plan_mode = True
    runtime.tools_registry.register(
        ToolSpec("exit_plan_mode", "Submit plan", {"type": "object", "properties": {"plan": {"type": "string"}},
                                                  "required": ["plan"]}, ToolPermission.READ),
        parent_handler,
    )
    runtime.model = ScriptedModel([
        ModelResponse(tool_calls=[ToolCall("exit_plan_mode", {"plan": "# Child plan\nRead the evidence."}, "plan-1")]),
        ModelResponse(text="Plan sent to the parent."),
    ])
    result = runtime.subagents.run("architect", "Propose a plan")
    assert result.error is None
    assert runtime.plan_mode and parent_plans == []
    assert legacy_tools._plan_mode_handler is parent_handler
    plans = [event for event in runtime.persisted if event.payload.get("activity", {}).get("kind") == "plan.created"]
    assert len(plans) == 1
    assert plans[0].payload["activity"]["payload"]["plan_markdown"] == "# Child plan\nRead the evidence."


def test_unexpected_child_setup_failure_emits_one_terminal_and_releases_scope(runtime, monkeypatch):
    def fail():
        raise RuntimeError("Instruction setup failed")

    monkeypatch.setattr(runtime.instructions, "build", fail)
    result = runtime.subagents.run("tester", "Check setup")
    assert result.error == "Instruction setup failed"
    assert not runtime.subagents.is_child_thread
    assert [event.kind for event in runtime.persisted] == [EventKind.SUBAGENT_STARTED, EventKind.SUBAGENT_FAILED]
    assert runtime.persisted[-1].payload["error"] == result.error


def test_stop_is_shared_and_child_status_is_cancelled(runtime):
    class CancelModel:
        def complete(self, request, on_chunk=None):
            runtime._cancellation_flag.set()
            return ModelResponse(text="This result must not complete the stopped child.")

    runtime.model = CancelModel()
    result = runtime.subagents.run("architect", "Review design")
    assert result.summary == "Agent execution was interrupted."
    assert runtime.persisted[-1].payload["subagent"]["status"] == "cancelled"
    assert runtime.persisted[-1].kind == EventKind.SUBAGENT_FAILED


def test_parallel_scope_is_thread_local_and_survives_a_sibling_finishing(runtime):
    started = threading.Barrier(3)
    fast_finished = threading.Event()
    permission = SimpleNamespace(name="spawn_subagent", permission=ToolPermission.READ)

    def fast():
        with runtime.subagents.isolated_execution():
            started.wait(timeout=5)
            assert not runtime._check_tool_permission(permission, {})[0]
        fast_finished.set()

    def slow():
        with runtime.subagents.isolated_execution():
            started.wait(timeout=5)
            assert fast_finished.wait(timeout=5)
            assert runtime.subagents.is_child_thread
            return runtime._check_tool_permission(permission, {})

    with ThreadPoolExecutor(max_workers=2) as pool:
        fast_future, slow_future = pool.submit(fast), pool.submit(slow)
        started.wait(timeout=5)
        assert runtime._check_tool_permission(permission, {}) == (True, "read-only")
        fast_future.result(timeout=5)
        allowed, reason = slow_future.result(timeout=5)
        assert not allowed and "Nested" in reason
    assert not runtime.subagents.is_child_thread


def test_identical_parallel_tasks_keep_separate_ids_and_browser_prefixes():
    prompts = []

    def runner(role, history):
        prompts.append(history[0])
        return "Report"

    manager = SubagentManager(runner)
    results = manager.run_multi_parallel([{"role": "tester", "task": "Same task"}] * 2)
    assert len({result.agent_id for result in results}) == 2
    assert len({prompt.content for prompt in prompts}) == 2
    assert {prompt.metadata["subagent"]["agent_id"] for prompt in prompts} == {result.agent_id for result in results}


def test_parallel_child_model_requests_use_distinct_sdk_session_and_restore_parent(runtime):
    from kratos_agent.sdk.client import _cancel_context, _request_context, gateway_scope
    from kratos_agent.core.execution_control import current_cancel_event

    calls = []
    reached_model = threading.Barrier(2)

    class CaptureModel:
        def complete(self, request, on_chunk=None):
            calls.append((dict(_request_context.get()), _cancel_context.get(), current_cancel_event()))
            reached_model.wait(timeout=5)
            return ModelResponse(text="Verified independent report.")

    runtime.model = CaptureModel()
    with gateway_scope(session_id="parent-session", task_id="parent-task"):
        results = runtime.subagents.run_multi_parallel([{"role": "tester", "task": "Same task"}] * 2)
        assert dict(_request_context.get()) == {"x-session-id": "parent-session", "x-kratos-task-id": "parent-task"}
    expected_ids = {result.agent_id for result in results}
    assert {call[0]["x-session-id"] for call in calls} == {f"subagent:{agent_id}" for agent_id in expected_ids}
    assert {call[0]["x-kratos-task-id"] for call in calls} == expected_ids
    assert all(call[1] is runtime._cancellation_flag and call[2] is runtime._cancellation_flag for call in calls)


def test_parallel_child_tool_workers_cannot_spawn_nested_agents(runtime, monkeypatch):
    monkeypatch.setenv("KRATOS_PARALLEL_EXECUTION", "1")
    spawned = []
    runtime.tools_registry.register(
        ToolSpec("spawn_subagent", "Run child", {"type": "object", "properties": {
            "role": {"type": "string"}, "task": {"type": "string"}}, "required": ["role", "task"]}, ToolPermission.READ),
        lambda role, task: spawned.append((role, task)) or "nested report",
    )
    runtime.model = ScriptedModel([
        ModelResponse(tool_calls=[ToolCall("spawn_subagent", {"role": "tester", "task": task}, f"spawn-{i}")
                                  for i, task in enumerate(("First", "Second"))]),
        ModelResponse(text="Nested delegation was unavailable; the parent received the finding."),
    ])
    result = runtime.subagents.run("tester", "Inspect child nesting")
    assert result.error is None
    assert spawned == []
    failures = [event.payload["activity"]["payload"] for event in runtime.persisted
                if event.payload.get("activity", {}).get("kind") == "tool.failed"]
    assert len(failures) == 2 and all("Nested subagent spawning" in failure["content"] for failure in failures)


@pytest.mark.parametrize("kind,payload", [
    (EventKind.MODEL_THINKING, {"reasoning": "private thought"}),
    (EventKind.MODEL_RESPONSE, {"text": "intermediate answer", "display_text": "child-only prose", "usage": {"input_tokens": 5}}),
    (EventKind.REQUEST_ASSEMBLED, {"messages": ["system prompt"], "context_usage": {"used_tokens": 9}}),
])
def test_scoped_model_progress_omits_reasoning_and_transcript(kind, payload):
    event = RuntimeEvent(kind, payload, "child-turn", timestamp=42)
    scoped = scoped_subagent_event(event, {"agent_id": "child", "role": "tester", "task": "Review"}, "parent-turn")
    assert scoped.payload["child_turn_id"] == "child-turn"
    assert scoped.timestamp == 42
    assert "reasoning" not in scoped.payload["activity"]["payload"]
    assert "text" not in scoped.payload["activity"]["payload"]
    assert "display_text" not in scoped.payload["activity"]["payload"]
    assert "messages" not in scoped.payload["activity"]["payload"]
    assert event.payload == payload  # Original event is not rewritten.
