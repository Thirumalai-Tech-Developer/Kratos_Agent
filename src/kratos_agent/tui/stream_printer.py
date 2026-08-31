"""Stream printer — pipe-safe output helper.

When stdout is not a TTY (piped / redirected), all Rich markup and animations
are suppressed and plain text is written instead.  This ensures clean output for:

    kratos-agent "do X" | tee log.txt
    kratos-agent "do X" > output.txt
"""
from __future__ import annotations

import os
import sys
from typing import Optional


def is_interactive() -> bool:
    """True if we have a real terminal (not piped/redirected)."""
    if os.environ.get("KRATOS_NO_COLOR", "").lower() in ("1", "true", "yes"):
        return False
    if os.environ.get("NO_COLOR"):
        return False
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def is_no_color() -> bool:
    """True when color/animations should be suppressed."""
    return not is_interactive()


def plain_print(text: str, file=None) -> None:
    """Print stripped plain text (no Rich markup), always to stdout."""
    # Strip Rich markup tags
    import re
    clean = re.sub(r"\[/?[^\[\]]+\]", "", text)
    print(clean, file=file or sys.stdout, flush=True)


def pipe_print_step(status: str, label: str, detail: str = "", elapsed: str = "") -> None:
    """Print a structured step line in pipe-safe plain text format."""
    parts = [f"[{status.upper()}]", label]
    if elapsed:
        parts.append(f"({elapsed})")
    if detail:
        parts.append(detail)
    plain_print("  " + "  ".join(parts))


def pipe_print_tool(name: str, args: dict) -> None:
    """Print tool call in pipe-safe plain text format."""
    from .events import _redact
    plain_print(f"  [TOOL] {name}")
    for k, v in list(args.items())[:4]:
        plain_print(f"    {k}: {_redact(v, k)}")


def pipe_print_response(text: str) -> None:
    """Print the final assistant response in pipe-safe format."""
    print(text, flush=True)


def pipe_print_error(message: str) -> None:
    """Print an error in pipe-safe format."""
    plain_print(f"[ERROR] {message}", file=sys.stderr)
