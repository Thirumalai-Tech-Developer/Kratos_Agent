"""Terminal Code Highlighter & Dialog Component for Kratos CLI.

Implements high-fidelity syntax highlighting matching highlighter.js and
frontend MarkdownRenderer (CodeDialogBox) with language badges, line numbers,
file metadata, and monokai/dracula themes.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from rich.console import Console, Group
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

_EXTENSION_LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".pyw": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "jsx",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".sass": "sass",
    ".less": "less",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".svg": "xml",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".ps1": "powershell",
    ".psm1": "powershell",
    ".bat": "batch",
    ".cmd": "batch",
    ".sql": "sql",
    ".rs": "rust",
    ".go": "go",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cc": "cpp",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".md": "markdown",
    ".markdown": "markdown",
    ".dockerfile": "docker",
    ".env": "bash",
    ".ini": "ini",
    ".conf": "ini",
}


def detect_language(file_path: str = "", code: str = "") -> str:
    """Infers programming language from file extension or code content."""
    if file_path:
        suffix = Path(file_path).suffix.lower()
        if suffix in _EXTENSION_LANGUAGE_MAP:
            return _EXTENSION_LANGUAGE_MAP[suffix]
        base = Path(file_path).name.lower()
        if base in ("dockerfile", "containerfile"):
            return "docker"
        if base in ("makefile", "gnumakefile"):
            return "makefile"
        if base in (".env", ".env.local", ".env.example"):
            return "bash"

    if code:
        snippet = code[:800].strip()
        if re.search(r"^\s*<!DOCTYPE\s+html|<\s*html\b|<\s*div\b|<\s*head\b", snippet, re.IGNORECASE):
            return "html"
        if re.search(r"^\s*(import|from)\s+[\w.]+\s+(import|as)|def\s+\w+\s*\(|class\s+\w+.*:", snippet):
            return "python"
        if re.search(r"^\s*(const|let|var|function|export|import)\b|=>\s*\{", snippet):
            return "javascript"
        if re.search(r"\{[\s\S]*?[a-zA-Z-]+:\s*[^;]+;[\s\S]*?\}", snippet) and not re.search(r"def |function |class ", snippet):
            return "css"
        if snippet.startswith("{") and snippet.endswith("}"):
            return "json"
        if re.search(r"^\s*(npm|pnpm|yarn|pip|uv|curl|wget|git|cd|ls|mkdir|chmod)\b", snippet):
            return "bash"

    return "text"


def render_code_dialog(
    code: str,
    file_path: str = "",
    language: str = "",
    action: str = "CREATED FILE",
    max_preview_lines: int = 50,
    theme: str = "monokai",
) -> Panel:
    """Renders a styled terminal code dialog box matching the frontend highlighter component."""
    clean_code = code.strip()
    lang = language or detect_language(file_path, clean_code)
    lines = clean_code.splitlines()
    total_lines = len(lines)
    byte_count = len(clean_code.encode("utf-8"))

    # Truncate for terminal readability if excessively long
    is_truncated = False
    display_code = clean_code
    hidden_count = 0
    if total_lines > max_preview_lines:
        is_truncated = True
        hidden_count = total_lines - max_preview_lines
        display_code = "\n".join(lines[:max_preview_lines])

    # Syntax highlight using rich (Pygments engine)
    syntax_renderable = Syntax(
        display_code,
        lexer=lang,
        theme=theme,
        line_numbers=True,
        word_wrap=True,
        padding=0,
    )

    items = [syntax_renderable]

    if is_truncated:
        items.append(
            Text(
                f"\n  [dim yellow]... (+ {hidden_count} more lines in {Path(file_path).name or 'code'})[/dim yellow]",
                style="italic",
            )
        )

    # Header title
    fname = Path(file_path).name if file_path else "Code Snippet"
    header_title = (
        f"[bold #00ff9d]⚡ {action}[/bold #00ff9d]  "
        f"[bold white]{fname}[/bold white]  "
        f"[dim]·[/dim]  "
        f"[bold gold1]{lang.upper()}[/bold gold1] "
        f"[dim]({total_lines} lines, {byte_count:,} bytes)[/dim]"
    )

    subtitle = f"[dim white]{file_path}[/dim white]" if file_path else ""

    return Panel(
        Group(*items),
        title=header_title,
        subtitle=subtitle,
        title_align="left",
        subtitle_align="right",
        border_style="cyan",
        padding=(1, 2),
    )


def print_code_dialog(
    code: str,
    file_path: str = "",
    language: str = "",
    action: str = "CREATED FILE",
    max_preview_lines: int = 50,
    console: Console | None = None,
) -> None:
    """Directly prints a syntax-highlighted code dialog box to the console."""
    if not code or not code.strip():
        return
    c = console or Console()
    panel = render_code_dialog(
        code=code,
        file_path=file_path,
        language=language,
        action=action,
        max_preview_lines=max_preview_lines,
    )
    c.print()
    c.print(panel)
    c.print()


def render_markdown_code_blocks(markdown_text: str, console: Console | None = None) -> None:
    """Finds all markdown code blocks and prints them using the high-fidelity syntax highlighter."""
    if not markdown_text or not markdown_text.strip():
        return
    c = console or Console()

    # Pattern to match ```lang\ncode\n```
    code_block_pattern = re.compile(r"```([a-zA-Z0-9_-]*)\n([\s\S]*?)```")
    last_end = 0

    has_code_block = bool(code_block_pattern.search(markdown_text))
    if not has_code_block:
        from rich.markdown import Markdown
        c.print(Markdown(markdown_text))
        return

    for match in code_block_pattern.finditer(markdown_text):
        start, end = match.span()
        # Print text preceding code block
        pre_text = markdown_text[last_end:start].strip()
        if pre_text:
            from rich.markdown import Markdown
            c.print(Markdown(pre_text))

        lang = match.group(1).strip()
        code_content = match.group(2)
        panel = render_code_dialog(
            code=code_content,
            language=lang,
            action="CODE GENERATED",
            max_preview_lines=45,
        )
        c.print(panel)
        last_end = end

    # Print remaining text
    post_text = markdown_text[last_end:].strip()
    if post_text:
        from rich.markdown import Markdown
        c.print(Markdown(post_text))
