"""Reject invalid tool arguments before permissions or side effects."""

from __future__ import annotations

import pytest

from kratos_agent.core.runtime_contracts import ToolCall, ToolPermission, ToolSpec
from kratos_agent.core.tool_runtime import (
    ToolRegistry,
    _signature_schema,
    legacy_tool_registry,
)


SCHEMA = {
    "type": "object",
    "properties": {
        "settings": {
            "type": "object",
            "properties": {
                "mode": {"enum": ["read", "write"]},
                "retries": {"type": "integer", "minimum": 0, "maximum": 3},
            },
            "required": ["mode", "retries"],
            "additionalProperties": False,
        },
        "paths": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "minItems": 1,
            "uniqueItems": True,
        },
        "enabled": {"type": "boolean"},
    },
    "required": ["settings", "paths", "enabled"],
    "additionalProperties": False,
}


def execute(schema, arguments):
    registry = ToolRegistry()
    calls = []
    approvals = []
    registry.register(
        ToolSpec(
            name="schema_probe",
            description="Test validation",
            parameters=schema,
            permission=ToolPermission.READ,
        ),
        lambda **kwargs: calls.append(kwargs) or "executed",
    )
    result = registry.execute(
        ToolCall(name="schema_probe", arguments=arguments),
        lambda spec, args: approvals.append(args) or (True, "allowed"),
    )
    return result, calls, approvals


@pytest.mark.parametrize(
    "field,value",
    [
        ("settings", {"mode": "delete", "retries": 1}),
        ("settings", {"mode": "read", "retries": "1"}),
        ("settings", {"mode": "read", "retries": True}),
        ("settings", {"mode": "read", "retries": -1}),
        ("settings", {"mode": "read", "retries": 4}),
        ("settings", {"mode": "read"}),
        ("settings", {"mode": "read", "retries": 1, "secret": "must-not-leak"}),
        ("paths", []),
        ("paths", ["a", "a"]),
        ("paths", [""]),
        ("paths", [1]),
        ("enabled", "true"),
    ],
)
def test_nested_invalid_arguments_never_execute(field, value):
    arguments = {
        "settings": {"mode": "read", "retries": 1},
        "paths": ["a"],
        "enabled": True,
    }
    arguments[field] = value
    result, calls, approvals = execute(SCHEMA, arguments)
    assert result.is_error
    assert not calls
    assert not approvals
    assert "must-not-leak" not in result.content


def test_valid_nested_arguments_execute_without_coercion():
    arguments = {
        "settings": {"mode": "write", "retries": 0},
        "paths": ["a", "b"],
        "enabled": False,
    }
    result, calls, approvals = execute(SCHEMA, arguments)
    assert not result.is_error
    assert calls == [arguments]
    assert approvals == [arguments]


@pytest.mark.parametrize(
    "value,valid",
    [("abc", True), (1, True), (None, True), (-1, False), ("a", False), (True, False)],
)
def test_local_references_and_union_schemas(value, valid):
    schema = {
        "type": "object",
        "$defs": {
            "value": {
                "anyOf": [
                    {"type": "string", "minLength": 3},
                    {"type": "integer", "minimum": 0},
                    {"type": "null"},
                ]
            }
        },
        "properties": {"value": {"$ref": "#/$defs/value"}},
        "required": ["value"],
    }
    result, calls, _ = execute(schema, {"value": value})
    assert result.is_error is not valid
    assert bool(calls) is valid


def test_remote_references_are_rejected_without_network(monkeypatch):
    import urllib.request

    def network_forbidden(*args, **kwargs):
        pytest.fail("Schema validation must not retrieve external resources")

    monkeypatch.setattr(urllib.request, "urlopen", network_forbidden)
    result, calls, approvals = execute(
        {
            "type": "object",
            "properties": {"value": {"$ref": "https://example.invalid/schema"}},
        },
        {"value": 1},
    )
    assert result.is_error
    assert not calls
    assert not approvals


@pytest.mark.parametrize(
    "schema", [{"type": "object", "properties": []}, {"type": "invalid"}]
)
def test_invalid_tool_schema_fails_closed(schema):
    result, calls, approvals = execute(schema, {})
    assert result.is_error
    assert not calls
    assert not approvals


@pytest.mark.parametrize("arguments", [[], None, False, "text"])
def test_non_object_arguments_are_rejected_without_raising(arguments):
    result, calls, approvals = execute(SCHEMA, arguments)
    assert result.is_error
    assert not calls
    assert not approvals


def test_non_finite_numbers_are_not_json_arguments():
    result, calls, approvals = execute(
        {"type": "object", "properties": {"value": {"type": "number"}}},
        {"value": float("nan")},
    )
    assert result.is_error
    assert not calls
    assert not approvals


def test_legacy_aliases_are_normalized_before_schema_validation():
    registry = ToolRegistry()
    calls = []
    registry.register(
        ToolSpec(
            name="write_file",
            description="Write",
            permission=ToolPermission.WRITE,
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["file_path", "content"],
                "additionalProperties": False,
            },
        ),
        lambda **args: calls.append(args) or "ok",
    )
    result = registry.execute(
        ToolCall(name="create_file", arguments={"path": "a.txt", "text": "hello"}),
        lambda spec, args: (True, "allowed"),
    )
    assert not result.is_error
    assert calls == [{"file_path": "a.txt", "content": "hello"}]


def test_signature_schema_preserves_native_parameter_types():
    def handler(
        label: str,
        count: int = 3,
        timeout: float = 0.5,
        enabled: bool = False,
        argv: list[str] | None = None,
    ):
        return "ok"

    schema = _signature_schema(handler)
    arguments = {
        "label": "test",
        "count": 4,
        "timeout": 1.5,
        "enabled": True,
        "argv": ["a", "b"],
    }
    result, calls, _ = execute(schema, arguments)
    assert not result.is_error
    assert calls == [arguments]
    arguments["argv"] = None
    assert not execute(schema, arguments)[0].is_error
    arguments["count"] = "4"
    assert execute(schema, arguments)[0].is_error


def test_signature_defaults_work_without_annotations():
    def handler(count=3, enabled=False, seconds=0.5):
        return "ok"

    result, calls, _ = execute(
        _signature_schema(handler), {"count": 2, "enabled": True, "seconds": 1.0}
    )
    assert not result.is_error
    assert calls


def test_legacy_manifest_boolean_is_corrected_from_handler_signature(tmp_path):
    registry = legacy_tool_registry(tmp_path)
    spec = registry.get("browser_screenshot").spec
    assert ToolRegistry._validate(spec, {"full_page": True})[0]
    assert not ToolRegistry._validate(spec, {"full_page": "true"})[0]
