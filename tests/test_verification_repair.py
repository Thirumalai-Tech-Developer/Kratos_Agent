"""A failed final check is a repair step, not an immediate terminal failure."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

from kratos_agent.core.agent_loop import AgentLoop
from kratos_agent.core.context_pipeline import ContextBuilder
from kratos_agent.core.instruction_engine import InstructionEngine, InstructionModule
from kratos_agent.core.runtime_contracts import ChatMessage, EventKind, ModelResponse, ToolCall, ToolPermission, ToolSpec
from kratos_agent.core.task_manager import AgentState
from kratos_agent.core.tool_runtime import ToolRegistry
from kratos_agent.core.verification_manager import VerificationResult


def make_loop(tmp_path, responses, verdicts):
    tools = ToolRegistry()
    def write_file(file_path, content):
        (tmp_path / file_path).write_text(content)
        return 'Saved.'
    tools.register(ToolSpec('write_file', 'Write file', {'type': 'object', 'properties': {'file_path': {'type': 'string'}, 'content': {'type': 'string'}}, 'required': ['file_path', 'content']}, ToolPermission.WRITE), write_file)
    instructions = InstructionEngine()
    instructions.register(InstructionModule('base', 'system', lambda: 'Complete the request.'))
    scripted = iter(responses)
    requests = []
    def complete(request, **kwargs):
        requests.append(request)
        if 'Kratos Planner' in request.get('system', ''):
            return ModelResponse(text=json.dumps({'goal': 'Fix the app', 'tasks': [{'id': '1', 'title': 'Write app'}]}))
        return next(scripted)
    events = []
    loop = AgentLoop(ContextBuilder(), instructions, tools, SimpleNamespace(complete=complete), events.append, tmp_path)
    loop.verification_manager.verify_workspace = Mock(side_effect=verdicts)
    return loop, events, requests


def test_failed_verification_repairs_then_completes(tmp_path):
    loop, events, requests = make_loop(tmp_path, [
        ModelResponse(tool_calls=[ToolCall('write_file', {'file_path': 'app.py', 'content': 'broken'})]),
        ModelResponse(text='Done.'),
        ModelResponse(tool_calls=[ToolCall('write_file', {'file_path': 'app.py', 'content': 'fixed'})]),
        ModelResponse(text='Fixed and verified.'),
    ], [VerificationResult(False, 'Tests failed', ['pytest: assertion mismatch']), VerificationResult(True, 'Tests passed', files_checked=1)])
    result, _ = loop.run([ChatMessage('user', 'Fix Python command syntax and create app.py with the result')], lambda *_: (True, 'allowed'), max_steps=10)
    assert loop.current_plan.state == AgentState.COMPLETED
    assert result == 'Fixed and verified.'
    assert (tmp_path / 'app.py').read_text() == 'fixed'
    retries = [event for event in events if event.kind == EventKind.RETRY]
    assert retries[0].payload['attempt'] == 1
    assert EventKind.AGENT_FAILED not in [event.kind for event in events]
    assert any('pytest: assertion mismatch' in message['content'] for request in requests for message in request.get('messages', []))


def test_model_response_persists_display_prose_without_speech_markers(tmp_path):
    loop, events, _ = make_loop(tmp_path, [
        ModelResponse(text='Checking the source.[[speak]]Checking the source.[[/speak]]',
                      tool_calls=[ToolCall('write_file', {'file_path': 'app.py', 'content': 'verified'})]),
        ModelResponse(text='Done.'),
    ], [VerificationResult(True, 'Verified', files_checked=1)])
    result, _ = loop.run([ChatMessage('user', 'Fix Python syntax and create app.py')], lambda *_: (True, 'allowed'), max_steps=10)
    response = next(event for event in events if event.kind == EventKind.MODEL_RESPONSE)
    assert response.payload['display_text'] == 'Checking the source.'
    assert '[[speak]]' not in response.payload['display_text']
    assert result == 'Done.'


def test_persistent_verification_failure_has_bounded_retries_and_saved_work(tmp_path, monkeypatch):
    monkeypatch.setenv('KRATOS_AUTONOMOUS_RECOVERY', '0')
    monkeypatch.setenv('KRATOS_VERIFICATION_RETRIES', '2')
    loop, events, _ = make_loop(tmp_path, [
        ModelResponse(tool_calls=[ToolCall('write_file', {'file_path': 'app.py', 'content': 'saved work'})]),
        ModelResponse(text='Done.'), ModelResponse(text='Done.'), ModelResponse(text='Done.'),
    ], [VerificationResult(False, 'Tests still fail', ['existing test failed'])] * 3)
    result, _ = loop.run([ChatMessage('user', 'Fix Python command syntax and create app.py with the result')], lambda *_: (True, 'allowed'), max_steps=10)
    assert loop.current_plan.state == AgentState.FAILED
    assert '2 automatic repair attempts' in result
    assert 'Task incomplete: 1/1' not in result
    assert len([event for event in events if event.kind == EventKind.RETRY]) == 2
    assert (tmp_path / 'app.py').read_text() == 'saved work'


def test_stop_during_automatic_repair_stops_instead_of_retrying(tmp_path):
    loop, events, _ = make_loop(tmp_path, [
        ModelResponse(tool_calls=[ToolCall('write_file', {'file_path': 'app.py', 'content': 'saved'})]), ModelResponse(text='Done.'),
    ], [VerificationResult(False, 'Tests failed')])
    original = loop.emit_fn
    def emit(event):
        original(event)
        if event.kind == EventKind.RETRY:
            loop.cancel()
    loop.emit_fn = emit
    result, _ = loop.run([ChatMessage('user', 'Fix Python command syntax and create app.py with the result')], lambda *_: (True, 'allowed'), max_steps=10)
    assert 'interrupted' in result
    assert len([event for event in events if event.kind == EventKind.RETRY]) == 1


def test_stop_during_passed_verification_preserves_work_without_completing(tmp_path):
    loop, events, _ = make_loop(tmp_path, [
        ModelResponse(tool_calls=[ToolCall('write_file', {'file_path': 'app.py', 'content': 'saved work'})]),
        ModelResponse(text='Done.'),
    ], [])

    def verify(*args, **kwargs):
        loop.cancel()
        return VerificationResult(True, 'Passed', files_checked=1)

    loop.verification_manager.verify_workspace.side_effect = verify
    result, history = loop.run(
        [ChatMessage('user', 'Fix Python command syntax and create app.py with the result')],
        lambda *_: (True, 'allowed'), max_steps=5,
    )
    assert 'interrupted' in result.lower()
    assert (tmp_path / 'app.py').read_text() == 'saved work'
    assert any(message.role == 'tool' and message.content == 'Saved.' for message in history)
    assert loop.current_plan.state != AgentState.COMPLETED
    assert not any(event.kind in {EventKind.AGENT_COMPLETED, EventKind.TURN_COMPLETED} for event in events)
    assert any(event.kind == EventKind.TURN_FAILED and event.payload.get('error') == 'cancelled' for event in events)


def test_stop_during_final_model_completion_does_not_run_verification(tmp_path):
    loop, events, _ = make_loop(tmp_path, [
        ModelResponse(tool_calls=[ToolCall('write_file', {'file_path': 'app.py', 'content': 'saved work'})]),
        ModelResponse(text='Done.'),
    ], [VerificationResult(True, 'Passed', files_checked=1)])
    original = loop.model.complete

    def complete(request, **kwargs):
        response = original(request, **kwargs)
        if response.text == 'Done.':
            loop.cancel()
        return response

    loop.model.complete = complete
    result, history = loop.run(
        [ChatMessage('user', 'Fix Python command syntax and create app.py with the result')],
        lambda *_: (True, 'allowed'), max_steps=5,
    )
    assert 'interrupted' in result.lower()
    assert (tmp_path / 'app.py').read_text() == 'saved work'
    assert any(message.role == 'tool' and message.content == 'Saved.' for message in history)
    loop.verification_manager.verify_workspace.assert_not_called()
    assert not any(event.kind in {EventKind.AGENT_COMPLETED, EventKind.TURN_COMPLETED} for event in events)
    assert any(event.kind == EventKind.TURN_FAILED and event.payload.get('error') == 'cancelled' for event in events)


def test_continue_verifies_prior_outputs_without_requiring_new_file_writes(tmp_path):
    from kratos_agent.core.task_manager import ExecutionPlan, TaskItem, TaskState
    (tmp_path / 'app.py').write_text('print(42)')
    loop, events, requests = make_loop(tmp_path, [ModelResponse(text='Verified existing work.')], [VerificationResult(True, 'Passed', files_checked=1)])
    plan = ExecutionPlan(goal='Build app', tasks=[TaskItem(id='1', title='Write app', state=TaskState.COMPLETED)])
    loop.resume_files = ['app.py']
    result, _ = loop.run([ChatMessage('user', 'continue')], lambda *_: (True, 'allowed'), resume_plan=plan, max_steps=5)
    assert result == 'Verified existing work.'
    assert loop.current_plan.state == AgentState.COMPLETED
    assert loop.current_run.user_request == 'Build app'
    assert loop.verification_manager.verify_workspace.call_args.args[0] == ['app.py']
    assert loop.workspace_tracker.all_changed_files == []


def test_automatic_repair_continues_past_old_limit_and_verifies_real_work(tmp_path, monkeypatch):
    monkeypatch.setenv('KRATOS_VERIFICATION_RETRIES', '2')
    loop, events, _ = make_loop(tmp_path, [
        ModelResponse(tool_calls=[ToolCall('write_file', {'file_path':'app.py','content':'broken'})]),
        *[ModelResponse(text='Done.') for _ in range(4)],
        ModelResponse(tool_calls=[ToolCall('write_file', {'file_path':'app.py','content':'fixed'})]),
        ModelResponse(text='Fixed and verified.'),
    ], [VerificationResult(False,'Check still fails',['Repair is still required'])] * 4 + [VerificationResult(True,'Passed',files_checked=1)])
    result, _ = loop.run([ChatMessage('user','Fix Python command syntax and create app.py with the result')],lambda *_:(True,'allowed'),max_steps=12)
    assert result == 'Fixed and verified.'
    assert loop.current_plan.state == AgentState.COMPLETED
    assert (tmp_path/'app.py').read_text() == 'fixed'
    assert len([event for event in events if event.kind == EventKind.RETRY]) == 4
    assert not any(event.kind == EventKind.AGENT_FAILED for event in events)
