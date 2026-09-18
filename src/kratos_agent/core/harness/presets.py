"""DeepSeek Harness - 4 Signature Presets and Declarative Configuration."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


@dataclass
class HarnessPreset:
    """Configuration preset specifying enabled plugins, tools, model hyperparams, and directives."""

    name: str
    description: str
    enabled_plugins: Optional[List[str]] = None  # None means all available plugins
    allowed_tools: Optional[List[str]] = None  # None means unrestricted
    model_config: Dict[str, Any] = field(default_factory=dict)
    plugin_configs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    directives: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HarnessPreset":
        return cls(
            name=data.get("name", "custom"),
            description=data.get("description", ""),
            enabled_plugins=data.get("enabled_plugins"),
            allowed_tools=data.get("allowed_tools"),
            model_config=data.get("model_config", {}),
            plugin_configs=data.get("plugin_configs", {}),
            directives=data.get("directives", []),
        )


# ------------------------------------------------------------------------------
# Signature Preset Definitions
# ------------------------------------------------------------------------------

StandardPreset = HarnessPreset(
    name="standard",
    description="Full autonomous software engineering agent with cognitive memory, web search, git, and audit logging.",
    enabled_plugins=["tools", "memory", "deepseek_model", "audit", "creator"],
    allowed_tools=None,  # All registered tools
    model_config={
        "temperature": 0.5,
        "max_tokens": 32768,
        "thinking_enabled": True,
    },
    directives=[
        "You are operating in DeepSeek Harness Standard Mode.",
        "Balance comprehensive reasoning with autonomous tool execution.",
        "Utilize cognitive memory for long-term knowledge retention and task context.",
        "Parallel tool execution is enabled: emit multiple independent read/inspect/subagent tool calls concurrently in a single turn to save time.",
    ],
)

CodePreset = HarnessPreset(
    name="code",
    description="Precision coding & refactoring loop with surgical file modifications and strict verification.",
    enabled_plugins=["tools", "memory", "deepseek_model", "audit"],
    allowed_tools=[
        "read_file",
        "write_file",
        "edit_file",
        "replace_file_content",
        "multi_replace_file_content",
        "list_directory",
        "grep_search",
        "run_terminal_command",
        "spawn_subagent",
        "spawn_parallel_subagents",
        "read_skill",
        "list_skills",
        "read_symbol",
        "search_symbol",
        "view_outline",
        "git_status",
        "git_diff",
        "git_commit",
        "save_memory",
        "read_memory",
        "todo_write",
        "exit_plan_mode",
    ],
    model_config={
        "temperature": 0.1,
        "max_tokens": 32768,
        "thinking_enabled": True,
    },
    directives=[
        "You are operating in DeepSeek Harness Code Mode (Precision Refactoring Loop).",
        "Focus exclusively on surgical code editing, syntactic correctness, and automated testing.",
        "Prefer surgical replacements over rewriting entire files.",
        "Always execute verification commands (tests, linter, builds) after modifying code.",
        "Parallel tool execution is enabled: batch multi-file inspections and searches in a single turn to maximize throughput.",
    ],
)

MinimalPreset = HarnessPreset(
    name="minimal",
    description="Bare-metal benchmark and evaluation environment with minimal overhead.",
    enabled_plugins=["tools", "deepseek_model"],
    allowed_tools=[
        "read_file",
        "write_file",
        "run_terminal_command",
    ],
    model_config={
        "temperature": 0.0,
        "max_tokens": 32768,
        "thinking_enabled": False,
    },
    directives=[
        "You are operating in DeepSeek Harness Minimal Mode (Benchmark / Evaluation).",
        "Provide direct, concise responses with zero conversational filler.",
        "Execute commands directly and report exact outcomes.",
    ],
)

CreatorPreset = HarnessPreset(
    name="creator",
    description="Meta-programming runtime for authoring, hot-reloading, and inspecting agent plugins and tools.",
    enabled_plugins=["tools", "memory", "deepseek_model", "audit", "creator"],
    allowed_tools=None,  # All tools plus creator meta-tools
    model_config={
        "temperature": 0.3,
        "max_tokens": 32768,
        "thinking_enabled": True,
    },
    directives=[
        "You are operating in DeepSeek Harness Creator Mode (Meta-programming & Plugin Authoring).",
        "Design modular, self-contained plugins adhering to the HarnessPlugin lifecycle.",
        "Ensure all authored components have comprehensive tests and clear type signatures.",
        "Utilize runtime introspection to inspect kernel state and plugin health.",
    ],
)

PRESET_REGISTRY: Dict[str, HarnessPreset] = {
    "standard": StandardPreset,
    "code": CodePreset,
    "minimal": MinimalPreset,
    "creator": CreatorPreset,
}


def get_preset(name: str) -> Optional[HarnessPreset]:
    """Retrieve preset by name from registry."""
    return PRESET_REGISTRY.get(name.lower())


def register_preset(preset: HarnessPreset) -> None:
    """Register a new or custom preset."""
    PRESET_REGISTRY[preset.name.lower()] = preset


def load_preset_from_file(file_path: Union[str, Path]) -> HarnessPreset:
    """Load a custom preset from JSON or YAML file."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Preset file not found: {path}")

    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in [".yaml", ".yml"]:
        try:
            import yaml  # type: ignore

            data = yaml.safe_load(text)
        except ImportError:
            # Fallback naive yaml parsing for simple structures if pyyaml not installed
            import json

            data = json.loads(text)
    else:
        data = json.loads(text)

    preset = HarnessPreset.from_dict(data)
    register_preset(preset)
    return preset
