"""Model-visible discovery uses the live registry without running connectors."""
import json
from unittest.mock import Mock

from kratos_agent.core.runtime_contracts import ToolCall, ToolPermission, ToolSpec
from kratos_agent.core.tool_runtime import ToolRegistry, legacy_tool_registry


def names(schemas):
    return {schema["function"]["name"] for schema in schemas}


def add_gitdiagram(registry, handler):
    for name in ("get_repository_diagram", "find_repository_diagrams", "get_explainer_video", "resources_list", "resource_read"):
        registry.register(ToolSpec(
            name="mcp__GitDiagram__" + name,
            description="Inspect architecture and repositories with GitDiagram.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            permission=ToolPermission.READ,
            source="mcp:GitDiagram",
        ), handler)


def test_named_connector_survives_filter_category_and_crowded_catalog():
    registry = ToolRegistry()
    for index in range(50):
        registry.register(ToolSpec("ordinary_" + str(index), "General utility", {}, ToolPermission.READ), lambda: "unused")
    called = Mock()
    add_gitdiagram(registry, called)
    registry.register(ToolSpec("mcp__GitDiagram__browser_open", "Repository website", {}, ToolPermission.READ,
                               source="mcp:GitDiagram"), called)
    selected = registry.get_tools(context="Use gitdiagram to explain the architecture", categories=["FILES"], max_tools=10)
    assert len(selected) <= 10
    assert len([name for name in names(selected) if name.startswith("mcp__GitDiagram__")]) == 6
    called.assert_not_called()


def test_source_matching_is_case_insensitive_and_requires_whole_name():
    registry = ToolRegistry()
    add_gitdiagram(registry, Mock())
    assert registry._named_sources("use GITDIAGRAM") == {"mcp:GitDiagram"}
    assert registry._named_sources("an unrelated notgitdiagramtool") == set()


def test_live_discovery_is_always_advertised_and_observes_reloaded_tools(tmp_path):
    registry = legacy_tool_registry(tmp_path)
    called = Mock()
    add_gitdiagram(registry, called)
    assert "search_tools" in names(registry.get_tools(context="continue", max_tools=1))
    result = registry.execute(ToolCall("search_tools", {"query": "GitDiagram"}, "find-tools"), lambda *_: (True, ""))
    assert not result.is_error
    body = json.loads(result.content)
    assert len(body["tools"]) == 5
    assert all(tool["function"]["name"].startswith("mcp__GitDiagram__") for tool in body["tools"])
    assert all("parameters" in tool["function"] for tool in body["tools"])
    called.assert_not_called()
    for name in list(registry._tools):
        if name.startswith("mcp__GitDiagram__"):
            del registry._tools[name]
    empty = registry.execute(ToolCall("search_tools", {"query": "GitDiagram"}, "find-again"), lambda *_: (True, ""))
    assert not empty.is_error
    assert not json.loads(empty.content)["tools"]


def test_discovery_validates_limits_and_permission_before_reading_catalog(tmp_path):
    registry = legacy_tool_registry(tmp_path)
    for arguments in ({"query": ""}, {"query": "diagram", "max_results": 16}, {"query": "diagram", "extra": True}):
        result = registry.execute(ToolCall("search_tools", arguments, "invalid"), lambda *_: (True, ""))
        assert result.is_error
    result = registry.execute(ToolCall("search_tools", {"query": "diagram"}, "denied"), lambda *_: (False, "Denied"))
    assert result.is_error
    assert "Denied" in result.content
