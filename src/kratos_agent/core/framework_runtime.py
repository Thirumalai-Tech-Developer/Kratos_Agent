"""Adapters that let Kratos reuse installed agent frameworks instead of cloning them."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from typing import Any, Dict, List

from .runtime_contracts import ToolPermission, ToolSpec


class ExternalAgentFrameworks:
    """Discover and safely invoke installed OpenClaw and Claude Code CLIs."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()

    def available(self) -> Dict[str, str | None]:
        return {"openclaw": shutil.which("openclaw"), "claude-code": shutil.which("claude")}

    def import_integration(self, source: str, mcp_manager: Any, skill_manager: Any) -> Dict[str, Any]:
        """Import skills and MCP declarations from a framework or plugin bundle.

        The plugin's native code/hooks are left to its own framework. Kratos only
        consumes the interoperable Agent Skills and MCP surfaces.
        """
        source = source.strip()
        normalized = source.lower()
        imported_configs: List[Path] = []
        skill_count = 0

        if normalized in {"openclaw", "open-claw"}:
            mcp_manager.import_framework_config("openclaw")
            extension_root = Path.home() / ".openclaw" / "extensions"
            bundles = [path for path in extension_root.iterdir() if path.is_dir()] if extension_root.is_dir() else []
        elif normalized in {"claude", "claude-code", "claude_code"}:
            mcp_manager.import_framework_config("claude")
            plugin_root = Path.home() / ".claude" / "plugins" / "cache"
            bundles = [path for path in plugin_root.glob("*/*") if path.is_dir()] if plugin_root.is_dir() else []
            local_bundles = self.workspace / ".claude" / "plugins"
            if local_bundles.is_dir():
                bundles.extend(path for path in local_bundles.iterdir() if path.is_dir())
        else:
            path = Path(source).expanduser().resolve()
            if not path.exists():
                raise FileNotFoundError(f"Integration path not found: {path}")
            bundles = [path] if path.is_dir() else [path.parent]
            if path.is_file():
                mcp_manager.add_import(path)

        for bundle in bundles:
            candidates = [bundle / ".mcp.json", bundle / "mcp.json"]
            for config in candidates:
                if config.is_file() and config not in imported_configs:
                    mcp_manager.add_import(config)
                    imported_configs.append(config.resolve())
            if (bundle / "skills").is_dir() or (bundle / "commands").is_dir() or (bundle / "SKILL.md").is_file():
                try:
                    skill_count += skill_manager.add_source_root(bundle)
                except ValueError:
                    pass
        return {
            "source": source,
            "mcp_configs": [str(path) for path in imported_configs],
            "mcp_servers": len(mcp_manager.servers),
            "skills": skill_count,
        }

    def register_tools(self, registry: Any) -> bool:
        spec = ToolSpec(
            name="delegate_to_framework",
            description=(
                "Delegate one task to a locally installed OpenClaw or Claude Code agent runtime. "
                "The chosen framework uses its own configured model, plugins, skills, MCP tools, and permission settings. "
                "Use only when the user asks to use or delegate to an external agent framework. The task runs inside this workspace; it cannot deliver messages to channels."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "framework": {"type": "string", "enum": ["openclaw", "claude-code"]},
                    "prompt": {"type": "string", "minLength": 1, "description": "A bounded task for the external agent."},
                    "timeout_seconds": {"type": "integer", "default": 600, "minimum": 10, "maximum": 1800},
                    "max_turns": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
                },
                "required": ["framework", "prompt"],
                "additionalProperties": False,
            },
            permission=ToolPermission.EXECUTE,
            timeout_seconds=1800,
            source="framework-bridge",
        )
        registry.register(spec, self.delegate)
        return True

    def delegate(self, framework: str, prompt: str, timeout_seconds: int = 600, max_turns: int = 20) -> str:
        framework = framework.lower()
        if framework not in {"openclaw", "claude-code"}:
            raise ValueError("framework must be 'openclaw' or 'claude-code'")
        if not prompt.strip():
            raise ValueError("prompt must not be empty")

        executable = self.available().get(framework)
        if not executable:
            cli_name = "OpenClaw" if framework == "openclaw" else "Claude Code"
            raise RuntimeError(f"{cli_name} CLI is not installed or not on PATH")

        timeout = max(10, min(int(timeout_seconds), 1800))
        turn_limit = max(1, min(int(max_turns), 100))
        if framework == "openclaw":
            command = [executable, "agent", "exec", prompt, "--cwd", str(self.workspace), "--json", "--timeout", str(timeout)]
        else:
            command = [executable, "-p", prompt, "--output-format", "json", "--max-turns", str(turn_limit)]

        try:
            result = subprocess.run(
                command,
                cwd=self.workspace,
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"{framework} agent exceeded its {timeout}s timeout") from exc
        except OSError as exc:
            raise RuntimeError(f"Could not start {framework}: {type(exc).__name__}") from exc

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        if result.returncode:
            detail = stderr or stdout or f"exit code {result.returncode}"
            raise RuntimeError(f"{framework} agent failed ({result.returncode}): {detail[-4000:]}")
        if not stdout:
            raise RuntimeError(f"{framework} agent returned no output")
        # Keep structured output intact for downstream work and audit records.
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            return stdout[-12000:]
        return json.dumps(parsed, ensure_ascii=False, indent=2, default=str)[-12000:]
