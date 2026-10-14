"""Context controls must reduce prompts without deleting durable session history."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from kratos_agent.core.context_pipeline import ContextBudget, ContextBuilder
from kratos_agent.core.event_bus import event_bus
from kratos_agent.core.project_memory import ProjectMemory
from kratos_agent.core.runtime_contracts import ChatMessage, EventKind, ModelResponse, RuntimeEvent


def history():
    return [ChatMessage('user', 'Earlier request ' * 1500),
            ChatMessage('assistant', 'Older investigation findings ' * 2000),
            ChatMessage('user', 'Keep the current deliverable and run its tests.'),
            ChatMessage('assistant', '', metadata={'tool_calls': [{'id': 'call-1', 'function': {'name': 'read_file', 'arguments': '{}'}}]}),
            ChatMessage('tool', 'Recent file contents', tool_call_id='call-1')]


def test_estimate_counts_native_schemas_and_tool_arguments():
    builder = ContextBuilder()
    messages = [ChatMessage('assistant', '', metadata={'tool_calls': [{'arguments': 'x' * 8000}]})]
    tools = [{'function': {'description': 'schema' * 2000}}]
    request = builder.assemble('system', messages, tools, {})['request']
    assert request['token_estimate'] > 4000
    assert request['context_usage']['used_tokens'] == request['token_estimate']
    assert request['context_usage']['measurement'] == 'estimated'


def test_manual_compaction_reduces_tokens_and_preserves_tool_pairs_and_latest_request():
    builder = ContextBuilder()
    original = history()
    result, detail = builder.compact_history(original, force=True)
    assert detail['saved_tokens'] > 0
    assert detail['after_tokens'] < detail['before_tokens']
    assert original[2:] == result[-3:]
    assert result[0].metadata['compacted']
    assert builder.compaction_count == 1
    assert detail['reason'] == 'manual'
    assert len(original) == 5  # Caller-owned source history is not mutated.


def test_automatic_compaction_accounts_for_system_and_schema_overhead():
    builder = ContextBuilder(ContextBudget(max_input_tokens=24000, reserve_output_tokens=2000))
    built = builder.assemble('instructions ' * 6000, history(), [], {})
    assert built['compaction']['reason'] == 'automatic'
    assert built['request']['context_usage']['compaction_count'] == 1
    assert built['request']['token_estimate'] == builder.overhead_tokens + builder.history_tokens(built['history'])


def test_current_request_is_not_removed_when_it_alone_exceeds_budget():
    builder = ContextBuilder(ContextBudget(max_input_tokens=1000, reserve_output_tokens=100))
    original = [ChatMessage('user', 'Current objective ' * 2000)]
    built = builder.assemble('instructions', original, [], {})
    assert built['history'] == original
    assert built['compaction'] is None
    assert built['request']['context_usage']['over_limit']


def test_agent_loop_retains_compacted_history_for_the_next_step(tmp_path):
    from kratos_agent.core.agent_loop import AgentLoop
    from kratos_agent.core.tool_runtime import ToolRegistry

    builder = ContextBuilder(ContextBudget(max_input_tokens=4000, reserve_output_tokens=500))
    model = SimpleNamespace(complete=Mock(return_value=ModelResponse(text='Hello!')))
    loop = AgentLoop(builder, SimpleNamespace(build=lambda: []), ToolRegistry(), model, Mock(), tmp_path)
    original = history() + [ChatMessage('user', 'hi')]
    result, retained = loop.run(original, lambda *_: (True, 'allowed'))
    assert result == 'Hello!'
    assert retained[0].metadata['compacted']
    assert builder.history_tokens(retained) < builder.history_tokens(original)
    assert retained[-2].content == 'hi'


def test_provider_usage_is_not_reused_for_a_different_request():
    builder = ContextBuilder()
    builder.assemble('system', [ChatMessage('user', 'hi')], [], {})
    builder.record_usage({'prompt_tokens': 1234})
    assert builder.snapshot()['used_tokens'] == 1234
    assert builder.snapshot()['measurement'] == 'provider'
    assert builder.snapshot([ChatMessage('user', 'Next working context')])['measurement'] == 'estimated'
    builder.assemble('system', [ChatMessage('user', 'new request')], [], {})
    assert builder.snapshot()['provider_input_tokens'] is None
    builder.record_usage({'prompt_tokens': 0})
    assert builder.snapshot()['used_tokens'] == 0


@pytest.fixture
def runtime(tmp_path):
    # Extract the real methods without constructing main.py's global runtime,
    # which would connect the user's models and start configured MCP servers.
    source = Path(__file__).parents[1] / 'src/kratos_agent/main.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    klass = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'KratosRuntime')
    names = {'context_status', 'compact_context', '_save_context_checkpoint', '_restore_history', 'activate_session',
             '_refresh_project_instructions', '_project_instruction_message'}
    klass.body = [node for node in klass.body if isinstance(node, ast.FunctionDef) and node.name in names]
    recent = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_recent_conversation')
    namespace = {'ChatMessage': ChatMessage, 'Any': object, 'json': json, 'RuntimeEvent': RuntimeEvent,
                 'EventKind': EventKind, 'event_bus': event_bus}
    exec(compile(ast.Module(body=[klass, recent], type_ignores=[]), str(source), 'exec'), namespace)
    instance = namespace['KratosRuntime']()
    instance.workspace = tmp_path
    instance.context = ContextBuilder()
    instance._history = history()
    session = SimpleNamespace(session_id='session-test', updated_at='2026-10-10T10:00:00', turns=[{'user': 'Saved user', 'agent': 'Saved answer'}])
    instance.memory = SimpleNamespace(active_session=session)
    instance.model_name = 'model'
    instance.model_metadata = None
    instance._emit = Mock()
    instance.project_memory = ProjectMemory(tmp_path)
    instance._project_instruction_digest = instance.project_memory.snapshot_digest
    instance._pending_project_instruction_update = None
    instance._project_instruction_session = 'session-test'
    instance._event_store = SimpleNamespace(session_id='session-test')
    instance._open_event_store = Mock(return_value=instance._event_store)
    instance.recent = namespace['_recent_conversation']
    return instance


def test_manual_checkpoint_survives_session_reload_without_changing_saved_turns(runtime):
    saved_turns = json.dumps(runtime.memory.active_session.turns)
    result = runtime.compact_context()
    assert result['compacted']
    compacted = runtime._history
    runtime._history = []
    runtime.activate_session()
    assert runtime._history == compacted
    assert runtime.context.compaction_count == 1
    assert runtime.recent(runtime._history)[0].metadata['compacted']
    assert json.dumps(runtime.memory.active_session.turns) == saved_turns


def test_stale_checkpoint_does_not_replace_newer_conversation(runtime):
    runtime.compact_context()
    runtime.memory.active_session.updated_at = 'newer-version'
    assert runtime._restore_history() == [ChatMessage('user', 'Saved user'), ChatMessage('assistant', 'Saved answer')]


def test_failed_checkpoint_write_leaves_working_context_unchanged(runtime):
    original = runtime._history
    runtime._save_context_checkpoint = Mock(side_effect=OSError('disk unavailable'))
    with pytest.raises(OSError):
        runtime.compact_context()
    assert runtime._history is original
    assert runtime.context.compaction_count == 0
    runtime._emit.assert_not_called()


def test_empty_history_compaction_is_a_noop(runtime):
    runtime._history = []
    assert not runtime.compact_context()['compacted']
    assert not runtime.context_status()['can_compact']


def test_session_switch_discards_previous_live_plan_without_deleting_saved_turns(runtime):
    previous = runtime.memory.active_session
    saved_turns = json.dumps(previous.turns)
    runtime.loop = SimpleNamespace(current_plan={"goal":"Old chat"},current_run=object(),
        last_verification=object(),resume_files=["old.txt"],
        workspace_tracker=SimpleNamespace(reset=Mock()),terminal_latch=SimpleNamespace(reset=Mock()))
    runtime.memory.active_session = SimpleNamespace(session_id="fresh-chat",updated_at="fresh",turns=[])
    runtime._open_event_store.return_value = SimpleNamespace(session_id="fresh-chat")
    runtime.activate_session()
    assert runtime._history == []
    assert runtime.loop.current_plan is None and runtime.loop.current_run is None
    assert runtime.loop.last_verification is None and runtime.loop.resume_files == []
    runtime.loop.workspace_tracker.reset.assert_called_once()
    runtime.loop.terminal_latch.reset.assert_called_once()
    assert json.dumps(previous.turns) == saved_turns
