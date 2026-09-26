"""Pre-flight command linter to catch shell quoting collapse, unquoted metachars,
and destructive commands before execution.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from kratos_agent.utils.shell_quote import argv_for


@dataclass
class LintResult:
    ok: bool
    problems: list[str] = field(default_factory=list)
    shell: str = "powershell"
    code: str = "OK"
    suggestion: dict[str, Any] | None = None
    hint: str = ""

@dataclass
class QuoteBalanceError:
    quote: str
    index: int

INLINE_SOURCE_PATTERNS = [
    (re.compile(r"(?i)@(?:keyframes|property)\s+[a-zA-Z_-]+\s*\{"), "CSS source was embedded in the shell command."),
    (re.compile(r"(?i)\b(?:import|export)\s+(?:React|default|const|function)\b"), "JavaScript/TypeScript source was embedded in the shell command."),
    (re.compile(r"(?i)\b(?:createRoot|document\.querySelector|document\.createElement)\s*\("), "Browser JavaScript source was embedded in the shell command."),
    (re.compile(r"(?i)<(?:html|head|body|div|script|style)\b"), "HTML source was embedded in the shell command."),
    (re.compile(r"(?i)\b(?:Set-Content|Out-File|Add-Content)\b.*(?:\{|function|<script|@keyframes)"), "Source code was being transported through a PowerShell file-writing command."),
]


def contains_inline_source_code(cmd: str) -> str | None:
    """Detect source-code payloads that should use write_file/edit_file instead of a shell."""
    stripped = cmd.strip()
    if len(stripped) < 280:
        return None
    for pattern, reason in INLINE_SOURCE_PATTERNS:
        if pattern.search(stripped):
            return reason
    if re.search(r"(?i)\b(?:node|node\.exe)\s+-e\s+|\b(?:python|python3|py)(?:\.exe)?\s+-c\s+", stripped):
        return "A long inline script was embedded in the shell command."
    if len(stripped) > 1800 and any(tok in stripped for tok in ("{", "}", "=>", "function", "const ", "let ", "var ")):
        return "The command is large enough to be source transport rather than a normal shell command."
    return None

KNOWN_BAD = [
    (re.compile(r"\brm\s+-[a-zA-Z]*rf?\s+/\s*$", re.IGNORECASE), "Dangerous command: recursive root removal 'rm -rf /' is forbidden."),
    (re.compile(r"\bformat\s+[a-zA-Z]:", re.IGNORECASE), "Dangerous command: disk formatting is forbidden."),
    (re.compile(r"\bdel\b.*?\b[a-zA-Z]:\\", re.IGNORECASE), "Dangerous command: root filesystem deletion 'del /... C:\\' is forbidden."),
    (re.compile(r"Remove-Item\b.*?\b[a-zA-Z]:\\", re.IGNORECASE), "Dangerous command: recursive root deletion is forbidden."),
    (re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", re.IGNORECASE), "Dangerous command: fork bomb is forbidden."),
    (re.compile(r">\s*/dev/sd[a-z]", re.IGNORECASE), "Dangerous command: raw block overwrite is forbidden."),
    (re.compile(r"\bdd\s+if=", re.IGNORECASE), "Dangerous command: raw block copy 'dd' is forbidden."),
    (re.compile(r"\bmkfs", re.IGNORECASE), "Dangerous command: filesystem creation 'mkfs' is forbidden."),
]


def quote_balance(cmd: str, shell: str) -> QuoteBalanceError | None:
    """Finds unbalanced quotes in cmd."""
    s = shell.lower()
    in_single = False
    in_double = False
    single_idx = -1
    double_idx = -1

    i = 0
    while i < len(cmd):
        ch = cmd[i]
        if ch == "'" and not in_double:
            if s in ("powershell", "pwsh"):
                # In PowerShell, '' inside single quotes is an escaped quote
                if in_single and i + 1 < len(cmd) and cmd[i + 1] == "'":
                    i += 2
                    continue
            in_single = not in_single
            if in_single:
                single_idx = i
        elif ch == '"' and not in_single:
            # Check backtick escape in pwsh or backslash in bash
            if s in ("powershell", "pwsh") and i > 0 and cmd[i - 1] == "`" or s in ("bash", "sh", "zsh") and i > 0 and cmd[i - 1] == "\\":
                pass
            else:
                in_double = not in_double
                if in_double:
                    double_idx = i
        i += 1

    if in_single:
        return QuoteBalanceError(quote="'", index=single_idx)
    if in_double:
        return QuoteBalanceError(quote='"', index=double_idx)
    return None


def contains_prose(cmd: str) -> bool:
    """Checks if command contains natural-language sentences or non-Latin prose (like Tamil narration)."""
    # Check Tamil Unicode block
    if re.search(r"[\u0B80-\u0BFF]", cmd):
        return True
    # Check for long spoken sentences without command syntax
    if len(cmd.split()) > 8 and not any(k in cmd for k in ("=", "-", "/", "\\", "|", ">", "<", "$", ";")):
        return True
    return False


def unquoted_metachars(cmd: str) -> list[Any]:
    """Finds unquoted shell metacharacters like & or | in URLs or arguments."""
    problems = []
    # e.g., https://youtube.com/results?q=a&b without quotes
    url_match = re.search(r'(https?://[^\s"\']+&[^\s"\']+)', cmd)
    if url_match:
        problems.append(type("Meta", (), {"char": "&", "index": url_match.start()})())
    return problems


def suggest_argv(cmd: str, shell: str) -> dict[str, Any]:
    try:
        argv = argv_for(shell, cmd, prefer_encoded=True)
        return {"argv": argv}
    except Exception:
        return {"argv": ["powershell.exe", "-NoProfile", "-Command", cmd]}


def lint_command(cmd: str, shell: str = "powershell") -> LintResult:
    """Returns ok=False with a precise, actionable hint when the command would
    fail to parse. The hint goes straight back to the model as the tool result
    so it self-corrects on the next turn."""
    problems: list[str] = []
    code = "OK"

    # 1. Check Known Bad / Forbidden Targets
    for pat, msg in KNOWN_BAD:
        if pat.search(cmd):
            return LintResult(
                ok=False,
                problems=[msg],
                shell=shell,
                code="FORBIDDEN_TARGET",
                hint="Do not execute destructive commands targeting system roots or formatting drives.",
            )

    # 2. Reject source-code transport before the shell parser sees it.
    inline_source = contains_inline_source_code(cmd)
    if inline_source:
        return LintResult(
            ok=False,
            problems=[inline_source],
            shell=shell,
            code="SOURCE_AS_COMMAND",
            suggestion={
                "recommended_tools": ["write_file", "edit_file"],
                "reason": "Write source directly to a UTF-8 file, then run a short build/test command.",
            },
            hint=(
                "Do not transport application source through PowerShell, cmd.exe, node -e, or python -c. "
                "Use write_file/edit_file for the source, then run a short verification command."
            ),
        )

    # 3. Quote balance, per dialect
    bal = quote_balance(cmd, shell)
    if bal is not None:
        idx = bal.index
        ctx = cmd[max(0, idx - 25): min(len(cmd), idx + 25)]
        problems.append(
            f"unbalanced {bal.quote} starting at index {idx} "
            f"(context: …{ctx}…). "
            f"Use utils.shell_quote.quote_{shell}() or pass argv instead."
        )

    # 3. Common malformed URL prefixes generated by LLMs.
    if re.search(r"(?i)\bhttps//|\bhttp//", cmd):
        problems.append("malformed URL scheme detected; use https:// or http://.")

    # 4. Raw whitespace inside an unquoted URL
    for m in re.finditer(r"https?://\S*\s\S*", cmd):
        problems.append(
            f"URL at index {m.start()} contains a raw space — "
            f"url-encode it with urllib.parse.quote_plus()."
        )

    # 5. Unencoded shell metacharacters outside quotes
    if shell.lower() in ("cmd", "cmd.exe", "powershell", "pwsh"):
        for m in unquoted_metachars(cmd):
            problems.append(
                f"unquoted '{m.char}' at index {m.index} will be "
                f"interpreted by {shell}. Quote it or use argv."
            )

    # 6. Natural-language text in a command (e.g. Tamil narration leak)
    if contains_prose(cmd):
        problems.append(
            "this command appears to contain natural-language prose. "
            "Narration must never be interpolated into a shell command."
        )

    # 7. Non-ASCII in a cmd.exe command
    if shell.lower().startswith("cmd") and any(ord(c) > 127 for c in cmd):
        problems.append(
            "non-ASCII characters in a cmd.exe command will be mangled "
            "by the active code page. Use powershell -EncodedCommand "
            "(utils.shell_quote.powershell_encoded) instead."
        )

    if problems:
        return LintResult(
            ok=False,
            problems=problems,
            shell=shell,
            code="COMMAND_PARSE_RISK",
            suggestion=suggest_argv(cmd, shell),
            hint="Re-issue using the suggested argv, or quote the payload with utils.shell_quote.quote_powershell().",
        )

    return LintResult(ok=True, problems=[], shell=shell, code="OK", suggestion=suggest_argv(cmd, shell))
