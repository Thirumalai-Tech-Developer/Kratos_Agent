"""Normalized tool catalog index for Kratos Agent (supporting 181+ tools)."""
from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ToolMetadata:
    """Normalized metadata for a single tool in the Kratos catalog."""
    name: str
    description: str
    category: str
    capabilities: list[str] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    arguments: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    risk_level: str = "low"  # low, medium, high, destructive
    platform: str = "windows"
    requirements: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "capabilities": self.capabilities,
            "parameters": self.parameters,
            "arguments": self.arguments,
            "examples": self.examples,
            "risk_level": self.risk_level,
            "platform": self.platform,
            "requirements": self.requirements,
            "keywords": self.keywords,
            "aliases": self.aliases,
        }


class ToolIndex:
    """Stores and indexes all registered tools for high-speed dynamic semantic discovery."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolMetadata] = {}
        self._categories: dict[str, list[str]] = {}
        self._initialized = False

    def register(self, meta: ToolMetadata) -> None:
        self._tools[meta.name] = meta
        cat = meta.category.upper()
        if cat not in self._categories:
            self._categories[cat] = []
        if meta.name not in self._categories[cat]:
            self._categories[cat].append(meta.name)

    def get(self, name: str) -> ToolMetadata | None:
        return self._tools.get(name)

    def list_all(self) -> list[ToolMetadata]:
        return list(self._tools.values())

    def initialize_from_catalog(self, json_path: Path | None = None) -> None:
        """Loads and indexes the complete 181+ tool catalog from tools_list.json."""
        if self._initialized:
            return

        if json_path is None:
            json_path = Path(__file__).resolve().parent.parent / "utils" / "tools_list.json"

        if json_path.exists():
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                tool_list = data.get("tools", [])
                for t in tool_list:
                    name = t.get("name") or t.get("func_name", "")
                    if not name:
                        continue

                    desc = t.get("description", "")
                    params = t.get("parameters", {})
                    args = list(params.get("properties", {}).keys()) if isinstance(params, dict) else []

                    # Classify category and keywords
                    n_lower = name.lower()
                    desc_lower = desc.lower()

                    if any(k in n_lower or k in desc_lower for k in ("browser", "playwright", "url", "navigate", "tab", "web", "youtube")):
                        cat = "BROWSER"
                        keywords = ["browser", "navigate", "open url", "web", "click", "page", "youtube"]
                        reqs = ["browser"]
                    elif any(k in n_lower or k in desc_lower for k in ("click", "type", "key", "mouse", "window", "desktop", "focus", "app")):
                        cat = "COMPUTER"
                        keywords = ["gui", "desktop", "mouse", "keyboard", "window", "click", "type"]
                        reqs = ["gui"]
                    elif any(k in n_lower or k in desc_lower for k in ("file", "directory", "read", "write", "edit", "grep")):
                        cat = "FILES"
                        keywords = ["file", "directory", "read", "write", "code", "inspect"]
                        reqs = ["filesystem"]
                    elif any(k in n_lower or k in desc_lower for k in ("terminal", "command", "bash", "powershell", "git", "npm", "pytest")):
                        cat = "CODE"
                        keywords = ["terminal", "command", "run", "test", "git", "exec"]
                        reqs = ["terminal"]
                    elif any(k in n_lower or k in desc_lower for k in ("memory", "recall", "remember", "workflow")):
                        cat = "MEMORY"
                        keywords = ["memory", "recall", "remember", "context"]
                        reqs = []
                    elif any(k in n_lower or k in desc_lower for k in ("search", "find", "google", "ddg", "lookup")):
                        cat = "SEARCH"
                        keywords = ["search", "web", "research", "find"]
                        reqs = ["network"]
                    else:
                        cat = "GENERAL"
                        keywords = ["utility", "general"]
                        reqs = []

                    meta = ToolMetadata(
                        name=name,
                        description=desc,
                        category=cat,
                        parameters=params,
                        arguments=args,
                        requirements=reqs,
                        keywords=keywords,
                    )
                    self.register(meta)

                self._initialized = True
            except Exception as exc:
                logger.debug("Operation error suppressed: %s", exc)


# Global ToolIndex singleton
_global_tool_index: ToolIndex | None = None


def get_tool_index() -> ToolIndex:
    global _global_tool_index
    if _global_tool_index is None:
        _global_tool_index = ToolIndex()
        _global_tool_index.initialize_from_catalog()
    return _global_tool_index
