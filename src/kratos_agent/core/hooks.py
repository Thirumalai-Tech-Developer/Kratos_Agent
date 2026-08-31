"""
Hooks System for Kratos Agent — Claude Code-style pre/post tool hooks.

Hooks are configured in .kratos/hooks.json:
{
  "pre_tool_call": [
    {"type": "shell", "command": "echo pre_tool_call {tool} {input}"},
    {"type": "shell", "command": "python my_hook.py {tool}"}
  ],
  "post_tool_call": [
    {"type": "shell", "command": "echo post_tool_call {tool}"}
  ],
  "on_session_start": [],
  "on_session_end": []
}

Placeholders: {tool}, {input}, {output}, {session_id}
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List

from rich.console import Console

console = Console(highlight=False)

HOOKS_FILE = Path(".kratos/hooks.json")

HOOK_EVENTS = ["pre_tool_call", "post_tool_call", "on_session_start", "on_session_end"]


class HookRegistry:
    """Loads and fires pre/post tool hooks from .kratos/hooks.json."""

    def __init__(self):
        self._hooks: Dict[str, List[Dict]] = {e: [] for e in HOOK_EVENTS}
        self._python_hooks: Dict[str, List[Callable]] = {e: [] for e in HOOK_EVENTS}
        self._load()

    def _load(self):
        """Load hook definitions from .kratos/hooks.json."""
        try:
            if HOOKS_FILE.exists():
                data = json.loads(HOOKS_FILE.read_text(encoding="utf-8"))
                for event in HOOK_EVENTS:
                    raw = data.get(event, [])
                    if isinstance(raw, list):
                        self._hooks[event] = raw
        except Exception:
            pass

    def register(self, event: str, fn: Callable):
        """Register a Python callable hook for an event."""
        if event in self._python_hooks:
            self._python_hooks[event].append(fn)

    def _render_template(self, template: str, ctx: Dict[str, Any]) -> str:
        """Replace {placeholders} in hook command template."""
        for key, val in ctx.items():
            template = template.replace(f"{{{key}}}", str(val)[:200])
        return template

    def fire(
        self,
        event: str,
        tool: str = "",
        input_str: str = "",
        output_str: str = "",
        session_id: str = "",
    ):
        """
        Fire all hooks for the given event.
        Shell hooks run as subprocesses; Python hooks called directly.
        """
        ctx = {
            "tool": tool,
            "input": input_str[:200],
            "output": output_str[:200],
            "session_id": session_id,
        }

        # Fire shell hooks from hooks.json
        for hook_def in self._hooks.get(event, []):
            hook_type = hook_def.get("type", "shell")
            if hook_type == "shell":
                cmd_template = hook_def.get("command", "")
                if not cmd_template:
                    continue
                cmd = self._render_template(cmd_template, ctx)
                try:
                    result = subprocess.run(
                        cmd, shell=True, capture_output=True, text=True, timeout=10,
                        encoding="utf-8", errors="replace"
                    )
                    if result.returncode != 0 and result.stderr:
                        console.print(f"[dim yellow][hook:{event}] {result.stderr.strip()[:200]}[/dim yellow]")
                except Exception as exc:
                    console.print(f"[dim red][hook:{event}] error: {exc}[/dim red]")

        # Fire Python callable hooks
        for fn in self._python_hooks.get(event, []):
            try:
                fn(tool=tool, input_str=input_str, output_str=output_str, session_id=session_id)
            except Exception as exc:
                console.print(f"[dim red][hook:{event}] Python hook error: {exc}[/dim red]")

    def reload(self):
        """Reload hooks from disk."""
        self._hooks = {e: [] for e in HOOK_EVENTS}
        self._load()

    def create_example_hooks_file(self):
        """Create a starter .kratos/hooks.json if one doesn't exist."""
        if HOOKS_FILE.exists():
            return
        example = {
            "pre_tool_call": [
                {"type": "shell", "command": "echo '[kratos-hook] pre_tool_call: {tool}'"}
            ],
            "post_tool_call": [],
            "on_session_start": [],
            "on_session_end": [
                {"type": "shell", "command": "echo '[kratos-hook] session ended'"}
            ]
        }
        try:
            HOOKS_FILE.parent.mkdir(parents=True, exist_ok=True)
            HOOKS_FILE.write_text(json.dumps(example, indent=2), encoding="utf-8")
            console.print(f"[dim]Created example hooks file: {HOOKS_FILE}[/dim]")
        except Exception:
            pass


# Global singleton
hook_registry = HookRegistry()
