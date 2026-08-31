"""
KRATOS.md Project Memory — Claude Code CLAUDE.md equivalent.

On every session start, Kratos:
  1. Searches workspace root (and parents) for KRATOS.md or CLAUDE.md
  2. Reads and injects the file content into the system prompt
  3. If no KRATOS.md exists, auto-generates one with project summary

The KRATOS.md file is the developer's persistent project instructions.
It can contain: tech stack, coding conventions, key commands, architecture notes.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional


_KRATOS_MD_NAMES = ["KRATOS.md", "CLAUDE.md", "AGENTS.md", ".kratos/PROJECT.md"]


def _discover_memory_file(start: Optional[Path] = None) -> Optional[Path]:
    """Walk from start dir upwards looking for a project memory file."""
    cwd = start or Path.cwd()
    search_root = Path(cwd.anchor)  # Don't go above filesystem root
    current = cwd
    while current >= search_root:
        for name in _KRATOS_MD_NAMES:
            candidate = current / name
            if candidate.exists() and candidate.is_file():
                return candidate
        if current == current.parent:
            break
        current = current.parent
    return None


def _auto_generate_kratos_md(target: Path) -> str:
    """Generate a default KRATOS.md from workspace analysis."""
    lines = [
        "# KRATOS Project Memory",
        "",
        "> This file is read by Kratos Agent on every session start.",
        "> Edit it to give Kratos persistent project-specific instructions.",
        "",
        "## Project Overview",
        "",
    ]

    # Try to infer project type
    cwd = target.parent
    markers = {
        "Python (uv/pip)": ["pyproject.toml", "setup.py", "requirements.txt"],
        "Node.js": ["package.json"],
        "Rust": ["Cargo.toml"],
        "Go": ["go.mod"],
        "Java": ["pom.xml", "build.gradle"],
        "Ruby": ["Gemfile"],
    }
    detected = []
    for lang, files in markers.items():
        if any((cwd / f).exists() for f in files):
            detected.append(lang)

    if detected:
        lines.append(f"**Tech Stack:** {', '.join(detected)}")
    else:
        lines.append("**Tech Stack:** (auto-detected — please update)")

    # Try to get project name from pyproject.toml or package.json
    project_name = cwd.name
    try:
        pp = cwd / "pyproject.toml"
        if pp.exists():
            import re
            content = pp.read_text(encoding="utf-8")
            m = re.search(r'^name\s*=\s*["\'](.+?)["\']', content, re.MULTILINE)
            if m:
                project_name = m.group(1)
    except Exception:
        pass

    lines += [
        f"**Project Name:** {project_name}",
        f"**Workspace Root:** {cwd}",
        "",
        "## Key Commands",
        "",
        "```bash",
        "# Add your key commands here",
        "# e.g. uv run kratos-agent",
        "```",
        "",
        "## Coding Conventions",
        "",
        "- (Add your team coding conventions here)",
        "",
        "## Architecture Notes",
        "",
        "- (Describe high-level architecture here)",
        "",
        "## Important Notes for Kratos",
        "",
        "- (Add any persistent instructions for the AI here)",
    ]

    content = "\n".join(lines)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except Exception:
        pass
    return content


class ProjectMemory:
    """Loads and provides project-level memory context for Kratos."""

    def __init__(self, workspace: Optional[str] = None):
        self._workspace = Path(workspace) if workspace else Path.cwd()
        self._file: Optional[Path] = None
        self._content: str = ""
        self._loaded = False

    def _ensure_loaded(self):
        if self._loaded:
            return
        self._loaded = True
        found = _discover_memory_file(self._workspace)
        if found:
            self._file = found
            try:
                self._content = found.read_text(encoding="utf-8", errors="replace").strip()
            except Exception:
                self._content = ""
        else:
            # Auto-create KRATOS.md
            target = self._workspace / "KRATOS.md"
            self._content = _auto_generate_kratos_md(target)
            self._file = target

    def get_project_context(self) -> str:
        """Returns the full project memory block for injection into system prompt."""
        self._ensure_loaded()
        if not self._content:
            return ""
        file_label = str(self._file) if self._file else "KRATOS.md"
        return (
            f"\n\n---\n## Project Memory ({file_label})\n\n"
            f"{self._content}\n\n---\n"
        )

    @property
    def file_path(self) -> Optional[Path]:
        self._ensure_loaded()
        return self._file

    def reload(self):
        """Force reload of project memory file."""
        self._loaded = False
        self._ensure_loaded()


# Global singleton
project_memory = ProjectMemory()
