from types import SimpleNamespace

import pytest

from kratos_agent.core.model_guard import OutputGuard, ProgressGuard, RepetitiveOutputError, repetitive_output
from kratos_agent.core.generation_settings import GenerationSettings
from kratos_agent.core.runtime_contracts import ToolCall, ToolResult
from kratos_agent.brain.client import BrainClient
from unittest.mock import MagicMock, patch
from kratos_agent.core.agent_loop import AgentLoop
from kratos_agent.core.context_pipeline import ContextBuilder
from kratos_agent.core.runtime_contracts import ChatMessage, ModelResponse, EventKind


def test_runaway_webgl_text_is_detected_across_small_chunks():
    text = 'WebGL 2.0 (' * 80
    assert repetitive_output(text)
    guard = OutputGuard()
    with pytest.raises(RepetitiveOutputError):
        for character in text:
            guard.push(character)


def test_small_repeats_and_normal_code_are_not_flagged():
    assert not repetitive_output('yes yes yes yes')
    assert not repetitive_output(' ' * 1000)
    assert not repetitive_output('const result = items.map(item => item.name);\n' + 'function update() { return 42; }')


def test_identical_inspection_is_blocked_but_changed_evidence_and_edits_reset_it():
    guard = ProgressGuard('Fix index.html')
    call = ToolCall('read_file', {'file_path': 'index.html'})
    result = ToolResult(call.call_id, call.name, 'same contents')
    for _ in range(3):
        guard.observe(call, result)
    assert guard.repeated(call)
    blocked = ToolResult(call.call_id, call.name, 'Unchanged inspection blocked. Use previous evidence.', is_error=True)
    guard.observe(call, blocked)
    assert guard.repeated(call)
    guard.observe(call, blocked)
    assert guard.blocked == 3
    guard.observe(call, ToolResult(call.call_id, call.name, 'changed contents'))
    assert not guard.repeated(call)
    edit = ToolCall('edit_file', {'file_path': 'index.html'})
    guard.observe(edit, ToolResult(edit.call_id, edit.name, 'edited'))
    assert guard.reads == 0
    assert guard.blocked == 0


def test_readonly_task_allows_distinct_inspections_but_edit_task_gets_progress_warning():
    review = ProgressGuard('Explain the architecture', 4)
    edit = ProgressGuard('Fix the page', 4)
    for i in range(4):
        call = ToolCall('read_file', {'file_path': f'file{i}.py'})
        result = ToolResult(call.call_id, call.name, f'contents {i}')
        assert review.observe(call, result) is None
        warning = edit.observe(call, result)
    assert warning and 'requested edit' in warning


def test_terminal_reads_count_but_mutation_commands_do_not():
    guard = ProgressGuard('Fix site')
    assert guard.is_inspection(ToolCall('run_terminal_command', {'argv': ['powershell', '-Command', 'Get-ChildItem src']}))
    assert not guard.is_inspection(ToolCall('run_terminal_command', {'command': 'Copy-Item app.js dest; Get-ChildItem dest'}))


def test_capability_settings_persist_and_unsupported_options_are_rejected(tmp_path):
    settings = GenerationSettings(tmp_path)
    metadata = {'supported_parameters': ['temperature'], 'effort_tiers': ['low', 'high'], 'max_output_tokens': 4096}
    result = settings.update('model', metadata, {'temperature': 0.2, 'reasoning_effort': 'high', 'max_tokens': 1024, 'inspection_limit': 8})
    assert result['options'] == {'temperature': 0.2, 'reasoning_effort': 'high', 'max_tokens': 1024}
    assert GenerationSettings(tmp_path).status('model', metadata) == result
    assert not settings.status('model', {})['options']
    with pytest.raises(ValueError, match='temperature control'):
        settings.update('web-model', {}, {'temperature': 0.2})
    with pytest.raises(ValueError, match='Thinking effort'):
        settings.update('model', metadata, {'reasoning_effort': 'invented'})
    with pytest.raises(ValueError):
        settings.update('model', metadata, {'temperature': float('nan')})
    assert settings.update('model', metadata, {'temperature': None})['options'].get('temperature') is None


def test_generation_options_are_sent_only_for_selected_model(monkeypatch):
    monkeypatch.setenv('KRATOS_MODEL_PROVIDER', 'gateway')
    monkeypatch.setenv('KRATOS_RUNTIME_MODEL', 'model')
    monkeypatch.setenv('KRATOS_MODEL', 'model')
    client = BrainClient('http://127.0.0.1:9999/v1/chat/completions')
    client.generation_options = {'temperature': 0.2, 'reasoning_effort': 'high'}
    client.generation_model = 'model'
    assert client.build_envelope('model', [])['temperature'] == 0.2
    monkeypatch.setenv('KRATOS_MODEL', 'other-model')
    monkeypatch.setenv('KRATOS_RUNTIME_MODEL', 'other-model')
    assert 'temperature' not in client.build_envelope('other-model', [])


def test_bounded_loop_stops_duplicate_inspections_with_all_tool_results_recorded(tmp_path, monkeypatch):
    monkeypatch.setenv("KRATOS_AUTONOMOUS_RECOVERY", "0")
    model = MagicMock()
    model.complete.side_effect = [ModelResponse(text='', tool_calls=[ToolCall('read_file', {'file_path': 'app.py'}, call_id=f'call{i}')], finish_reason='tool_calls') for i in range(8)]
    tools = MagicMock()
    tools.schemas.return_value = [{'name': 'read_file'}]
    tools.get.return_value = None
    tools.execute.side_effect = lambda call, allow_tool: ToolResult(call.call_id, call.name, 'unchanged source')
    instructions = MagicMock()
    instructions.build.return_value = [{'name': 'core', 'content': 'Help user'}]
    events = []
    loop = AgentLoop(context=ContextBuilder(), instructions=instructions, tools=tools, model=model, emit=events.append, workspace=tmp_path)
    with patch('kratos_agent.core.agent_loop.formulate_agent_plan', return_value=None):
        answer, history = loop.run([ChatMessage(role='user', content='Fix app.py')], allow_tool=lambda *args: (True, 'allowed'), max_steps=8)
    assert 'without progress' in answer, [(message.role, message.content) for message in history if message.role == 'tool']
    assert tools.execute.call_count == 3
    called_ids = {call['call_id'] for message in history for call in (message.metadata or {}).get('tool_calls', [])}
    result_ids = {message.tool_call_id for message in history if message.role == 'tool'}
    assert called_ids == result_ids
    assert any(event.kind == EventKind.TURN_FAILED and event.payload.get('error') == 'no_progress' for event in events)


def test_loop_recovers_repetition_once(tmp_path):
    model = MagicMock()
    model.complete.side_effect = [RepetitiveOutputError('repeat'), ModelResponse(text='Verified result.', tool_calls=[], finish_reason='stop')]
    tools = MagicMock()
    tools.schemas.return_value = []
    tools.get.return_value = None
    instructions = MagicMock()
    instructions.build.return_value = [{'name': 'core', 'content': 'Help user'}]
    loop = AgentLoop(context=ContextBuilder(), instructions=instructions, tools=tools, model=model, emit=lambda event: None, workspace=tmp_path)
    answer, _ = loop.run([ChatMessage(role='user', content='hello')], allow_tool=lambda *args: (True, 'allowed'), max_steps=4)
    assert answer == 'Verified result.'
    assert model.complete.call_count == 2


def test_settings_endpoint_applies_options_and_rejects_active_cli_turn(tmp_path):
    import threading
    from kratos_agent.web.server import KratosWebHandler
    runtime = SimpleNamespace(generation_settings=GenerationSettings(tmp_path), model_name='model',
        model_metadata={'supports_temperature': True}, brain=SimpleNamespace(), loop=SimpleNamespace(), _turn_lock=threading.Lock())
    replies = []
    handler = SimpleNamespace(server=SimpleNamespace(runtime=runtime, turn_lock=threading.Lock()),
        _send_json=lambda body, **kwargs: replies.append((body, kwargs.get('status', 200))))
    KratosWebHandler._handle_generation_settings(handler, {'temperature': 0.2, 'inspection_limit': 8})
    assert runtime.brain.generation_options == {'temperature': 0.2}
    assert runtime.loop.inspection_limit == 8
    assert replies[-1][1] == 200
    runtime._turn_lock.acquire()
    try:
        KratosWebHandler._handle_generation_settings(handler, {'temperature': 1})
        assert replies[-1][1] == 409
        assert runtime.brain.generation_options == {'temperature': 0.2}
    finally:
        runtime._turn_lock.release()
    KratosWebHandler._handle_generation_settings(handler, {'temperature': 9})
    assert replies[-1][1] == 400
    assert not handler.server.turn_lock.locked()


def test_invalid_saved_values_do_not_break_runtime(tmp_path):
    settings = GenerationSettings(tmp_path)
    settings.values = {'model': {'temperature': 'bad', 'max_tokens': 'bad', 'inspection_limit': -1}}
    assert settings.status('model', {'supports_temperature': True, 'max_output_tokens': 4096})['options'] == {}
    assert settings.status('model', {})['inspection_limit'] == 12
    settings.values['model'] = []
    assert settings.update('model', {}, {'inspection_limit': 8})['inspection_limit'] == 8


def test_persistent_recovery_changes_approach_without_reexecuting_blocked_reads(tmp_path):
    from kratos_agent.core.tool_runtime import ToolRegistry
    from kratos_agent.core.runtime_contracts import ToolPermission, ToolSpec

    source = tmp_path / "app.py"
    source.write_text("old contents", encoding="utf8")
    executed = []
    tools = ToolRegistry()
    params = {"type": "object", "properties": {"file_path": {"type": "string"}},
              "required": ["file_path"], "additionalProperties": False}
    def read_file(file_path):
        executed.append("read_file")
        return (tmp_path / file_path).read_text(encoding="utf8")
    def edit_file(file_path):
        executed.append("edit_file")
        (tmp_path / file_path).write_text("fixed contents", encoding="utf8")
        return "Updated file"
    tools.register(ToolSpec("read_file", "Read a file", params, ToolPermission.READ), read_file)
    tools.register(ToolSpec("edit_file", "Fix the isolated file", params, ToolPermission.WRITE), edit_file)
    model = MagicMock()
    model.complete.side_effect = [
        *[ModelResponse(tool_calls=[ToolCall("read_file", {"file_path": "app.py"})]) for _ in range(6)],
        ModelResponse(tool_calls=[ToolCall("edit_file", {"file_path": "app.py"})]),
        ModelResponse(text="File fixed.")
    ]
    events = []
    loop = AgentLoop(context=ContextBuilder(), instructions=SimpleNamespace(build=lambda: []),
                     tools=tools, model=model, emit=events.append, workspace=tmp_path)
    loop.cancellation_flag.wait = MagicMock(return_value=False)
    with patch("kratos_agent.core.agent_loop.formulate_agent_plan", return_value=None):
        answer, history = loop.run([ChatMessage("user", "Fix app.py")],
                                   allow_tool=lambda *args: (True, "allowed"), max_steps=10)
    assert answer == "File fixed."
    assert source.read_text(encoding="utf8") == "fixed contents"
    assert executed == ["read_file"] * 3 + ["edit_file"]
    assert any(event.kind == EventKind.RETRY and event.payload.get("strategy") == "fresh_plan"
               for event in events)
    assert any(request.args[0].get("tool_recovery_protocol") == "fresh_plan"
               for request in model.complete.call_args_list)
    assert not any(event.kind == EventKind.TURN_FAILED for event in events)
    assert any(message.role == "tool" and "blocked" in message.content.lower()
               for message in history)
