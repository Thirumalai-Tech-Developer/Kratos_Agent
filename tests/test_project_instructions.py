"""Project instructions are scoped, frozen per turn, and inherited by children."""

from __future__ import annotations

import ast
import threading
from functools import wraps
from pathlib import Path
from types import MethodType, SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from kratos_agent.core.instruction_engine import InstructionEngine, InstructionModule
from kratos_agent.core.project_memory import (
    PROJECT_INSTRUCTION_MAX_BYTES,
    ProjectInstructionConflict,
    ProjectMemory,
)
from kratos_agent.core.runtime_contracts import ChatMessage


def test_missing_project_file_does_not_scan_parents_or_create_a_file(tmp_path):
    (tmp_path / "kratos.md").write_text(
        "Parent guidance must not leak", encoding="utf-8"
    )
    workspace = tmp_path / "child"
    workspace.mkdir()
    (workspace / "CLAUDE.md").write_text(
        "Unselected compatibility file", encoding="utf-8"
    )
    (workspace / "AGENTS.md").write_text("Unselected developer file", encoding="utf-8")
    memory = ProjectMemory(workspace)
    assert memory.get_project_context() == ""
    assert memory.file_path is None
    assert memory.status()["exists"] is False
    assert not (workspace / "kratos.md").exists()
    assert not (workspace / "KRATOS.md").exists()


def test_root_alias_is_loaded_once_with_utf8_and_literal_references(tmp_path):
    (tmp_path / "KRATOS.md").write_bytes(
        b"\xef\xbb\xbf" + "Project café\n@../secret.md\nRun examples are text".encode()
    )
    memory = ProjectMemory(tmp_path)
    context = memory.get_project_context()
    assert "Project café" in context
    assert context.count("Project café") == 1
    assert "@../secret.md" in context
    assert "user's instructions take precedence" in context
    assert memory.status()["loaded"] is True
    assert memory.status(include_content=False).get("content") is None


def test_lowercase_root_file_takes_precedence_when_both_distinct_files_exist(tmp_path):
    primary, alias = tmp_path / "kratos.md", tmp_path / "KRATOS.md"
    primary.write_text("Primary project guidance", encoding="utf-8")
    if alias.exists():
        pytest.skip("Case-insensitive filesystems have one shared root file")
    alias.write_text("Alias guidance", encoding="utf-8")
    memory = ProjectMemory(tmp_path)
    assert "Primary project guidance" in memory.get_project_context()
    assert "Alias guidance" not in memory.get_project_context()


@pytest.mark.parametrize(
    "contents",
    [b"\xff\xfe invalid utf8", b"x" * (PROJECT_INSTRUCTION_MAX_BYTES + 1)],
    ids=["invalid_utf8", "oversized"],
)
def test_invalid_or_oversized_project_file_is_reported_without_partial_injection(
    tmp_path, contents
):
    path = tmp_path / "kratos.md"
    path.write_bytes(contents)
    memory = ProjectMemory(tmp_path)
    assert memory.get_project_context() == ""
    status = memory.status()
    assert status["exists"] is True and status["loaded"] is False
    assert status["error"]
    assert path.read_bytes() == contents


def test_external_edit_and_editor_status_do_not_change_frozen_prompt(tmp_path):
    path = tmp_path / "kratos.md"
    path.write_text("First revision", encoding="utf-8")
    memory = ProjectMemory(tmp_path)
    first = memory.get_project_context()
    path.write_text("Second revision", encoding="utf-8")
    assert memory.status()["content"] == "Second revision"
    assert memory.get_project_context() == first
    memory.reload()
    assert "Second revision" in memory.get_project_context()


def test_explicit_save_is_atomic_revision_checked_and_applies_only_after_reload(
    tmp_path,
):
    memory = ProjectMemory(tmp_path)
    assert memory.get_project_context() == ""
    created = memory.save("First revision")
    assert created["file_name"] == "kratos.md"
    assert created["exists"] and created["loaded"]
    assert memory.get_project_context() == ""
    memory.reload()
    saved = memory.save("Second revision", expected_digest=created["digest"])
    assert saved["digest"] != created["digest"]
    assert "First revision" in memory.get_project_context()
    with pytest.raises(ProjectInstructionConflict):
        memory.save("Stale editor content", expected_digest=created["digest"])
    assert memory.status()["content"] == "Second revision"
    assert not list(tmp_path.glob(".kratos-instructions-*.tmp"))


@pytest.mark.parametrize(
    "content",
    [None, 12, "🙂" * (PROJECT_INSTRUCTION_MAX_BYTES // 4 + 1), "\ud800"],
    ids=["none", "number", "oversized_utf8", "invalid_surrogate"],
)
def test_save_rejects_invalid_and_oversized_utf8_content_without_creating_file(
    tmp_path, content
):
    memory = ProjectMemory(tmp_path)
    with pytest.raises(ValueError):
        memory.save(content)
    assert not (tmp_path / "kratos.md").exists()


def test_symlink_cannot_read_or_overwrite_instructions_outside_workspace(tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("Outside guidance", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    try:
        (workspace / "kratos.md").symlink_to(outside)
    except OSError:
        pytest.skip("This Windows account cannot create symlinks")
    memory = ProjectMemory(workspace)
    assert memory.get_project_context() == ""
    assert "inside the workspace root" in memory.status()["error"]
    with pytest.raises(ValueError):
        memory.save("Do not overwrite outside")
    assert outside.read_text(encoding="utf-8") == "Outside guidance"


def runtime_methods():
    source = Path(__file__).parents[1] / "src/kratos_agent/main.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    runtime = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "KratosRuntime"
    )
    names = {
        "project_instruction_status",
        "_project_instruction_message",
        "_refresh_project_instructions",
        "_append_project_instruction_update",
        "_register_instruction_modules",
        "activate_session",
    }
    methods = [
        node
        for node in runtime.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    namespace = {
        "Any": Any,
        "ChatMessage": ChatMessage,
        "InstructionEngine": InstructionEngine,
        "InstructionModule": InstructionModule,
    }
    exec(
        compile(ast.Module(body=methods, type_ignores=[]), str(source), "exec"),
        namespace,
    )
    return {name: namespace[name] for name in names}


def runtime_stub(workspace):
    memory = ProjectMemory(workspace)
    memory.reload()
    instance = SimpleNamespace(
        workspace=workspace,
        project_memory=memory,
        _project_instruction_digest=memory.snapshot_digest,
        _pending_project_instruction_update=None,
        instructions=InstructionEngine(),
    )
    for name, method in runtime_methods().items():
        setattr(instance, name, MethodType(method, instance))
    instance._register_instruction_modules()
    return instance


def test_runtime_registers_project_layer_and_child_snapshot_inherits_identical_guidance(
    tmp_path,
):
    (tmp_path / "kratos.md").write_text(
        "Use the project architecture", encoding="utf-8"
    )
    instance = runtime_stub(tmp_path)
    parent = instance.instructions.build(active=["project-instructions"])
    assert parent[0]["layer"] == "project"
    assert "Use the project architecture" in parent[0]["content"]
    child = InstructionEngine()
    for section in parent:
        child.register(
            InstructionModule(
                section["name"],
                section["layer"],
                lambda content=section["content"]: content,
            )
        )
    (tmp_path / "kratos.md").write_text("Next-turn guidance", encoding="utf-8")
    assert (
        child.build()
        == parent
        == instance.instructions.build(active=["project-instructions"])
    )
    instance._refresh_project_instructions()
    assert (
        "Next-turn guidance"
        in instance.instructions.build(active=["project-instructions"])[0]["content"]
    )
    assert child.build() == parent


def test_changed_project_guidance_is_one_history_message_before_real_user_request(
    tmp_path,
):
    path = tmp_path / "kratos.md"
    path.write_text("First guidance", encoding="utf-8")
    instance = runtime_stub(tmp_path)
    path.write_text("Updated guidance", encoding="utf-8")
    instance._refresh_project_instructions()
    history = [
        ChatMessage("user", "Prior request"),
        ChatMessage("assistant", "Prior answer"),
        ChatMessage("user", "Actual next request"),
    ]
    instance._append_project_instruction_update(history, before_latest_user=True)
    assert history[-1].content == "Actual next request"
    assert "Updated guidance" in history[-2].content
    assert history[-2].metadata["project_instruction_update"]
    instance._refresh_project_instructions()
    instance._append_project_instruction_update(history, before_latest_user=True)
    assert (
        sum(
            message.metadata.get("project_instruction_update", False)
            for message in history
        )
        == 1
    )


def test_project_update_preserves_browser_cursor_and_sends_only_new_guidance(tmp_path):
    from kratos_agent.brain.browser_conversation import (
        completed_cursor,
        prepare_conversation,
    )
    from kratos_agent.sdk.client import KratosCompletion

    path = tmp_path / "kratos.md"
    path.write_text("First guidance", encoding="utf-8")
    instance = runtime_stub(tmp_path)
    first_system = instance.project_memory.get_project_context()
    _, cursor, _, _ = prepare_conversation(
        {
            "messages": [
                {"role": "system", "content": first_system},
                {"role": "user", "content": "Prior request"},
            ]
        }
    )
    previous = completed_cursor(
        cursor,
        {"conversation": {"conversation_id": "owned-chat"}},
        KratosCompletion("Prior answer"),
    )
    path.write_text("Updated guidance", encoding="utf-8")
    instance._refresh_project_instructions()
    history = [
        ChatMessage("user", "Prior request"),
        ChatMessage("assistant", "Prior answer"),
        ChatMessage("user", "Actual next request"),
    ]
    instance._append_project_instruction_update(history, before_latest_user=True)
    outgoing, _, continuing, _ = prepare_conversation(
        {
            "messages": [
                {
                    "role": "system",
                    "content": instance.project_memory.get_project_context(),
                },
                *[message.to_dict() for message in history],
            ]
        },
        previous,
    )
    assert continuing is True
    assert len(outgoing["messages"]) == 2
    assert "Updated guidance" in outgoing["messages"][0]["content"]
    assert outgoing["messages"][1]["content"] == "Actual next request"
    assert all(message["role"] == "user" for message in outgoing["messages"])


def test_removed_project_file_queues_clear_guidance_and_new_session_reloads(tmp_path):
    path = tmp_path / "kratos.md"
    path.write_text("First guidance", encoding="utf-8")
    instance = runtime_stub(tmp_path)
    path.unlink()
    instance._refresh_project_instructions()
    assert "no longer applies" in instance._pending_project_instruction_update
    path.write_text("Second session guidance", encoding="utf-8")
    instance.memory = SimpleNamespace(
        active_session=SimpleNamespace(session_id="second")
    )
    instance._project_instruction_session = "first"
    instance._event_store = SimpleNamespace(session_id="first")
    instance.context = SimpleNamespace(reset_tracking=Mock())
    instance._restore_history = Mock(return_value=[])
    instance._open_event_store = Mock(return_value=SimpleNamespace(session_id="second"))
    instance.activate_session()
    assert "Second session guidance" in instance.project_memory.get_project_context()
    assert instance._pending_project_instruction_update is None
    assert instance._project_instruction_session == "second"


def test_turn_wrapper_refreshes_project_snapshot_before_the_request(tmp_path):
    source = Path(__file__).parents[1] / "src/kratos_agent/main.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    node = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_serialize_turn"
    )
    namespace = {"wraps": wraps}
    exec(
        compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"),
        namespace,
    )
    (tmp_path / "kratos.md").write_text("Old turn guidance", encoding="utf-8")
    instance = runtime_stub(tmp_path)
    instance._turn_lock = threading.RLock()
    instance._cancellation_flag = threading.Event()
    instance.memory = SimpleNamespace(active_session=SimpleNamespace(session_id="one"))
    (tmp_path / "kratos.md").write_text("Current turn guidance", encoding="utf-8")
    wrapped = namespace["_serialize_turn"](
        lambda runtime: runtime.project_memory.get_project_context()
    )
    assert "Current turn guidance" in wrapped(instance)


def test_nested_chat_turn_keeps_snapshot_until_outer_turn_finishes(tmp_path):
    source = Path(__file__).parents[1] / "src/kratos_agent/main.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    node = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_serialize_turn"
    )
    namespace = {"wraps": wraps}
    exec(
        compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"),
        namespace,
    )
    path = tmp_path / "kratos.md"
    path.write_text("Frozen turn guidance", encoding="utf-8")
    instance = runtime_stub(tmp_path)
    instance._turn_lock = threading.RLock()
    instance._cancellation_flag = threading.Event()
    instance.memory = SimpleNamespace(active_session=SimpleNamespace(session_id="one"))
    inner = namespace["_serialize_turn"](
        lambda runtime: runtime.project_memory.get_project_context()
    )

    def run(runtime):
        path.write_text("Next turn guidance", encoding="utf-8")
        return inner(runtime)

    outer = namespace["_serialize_turn"](run)
    assert "Frozen turn guidance" in outer(instance)
    assert "Next turn guidance" in inner(instance)
    assert instance._project_instruction_turn_depth == 0
