"""Per-shell quoting and argv construction.
There is no universal quoting rule; anyone who tells you otherwise has not met PowerShell.
"""
from __future__ import annotations

import base64
import re
import shlex
from urllib.parse import quote_plus, urlencode, urlunsplit

_UNSAFE = re.compile(r"[^A-Za-z0-9_@%+=:,./-]")

def quote_powershell(s: str) -> str:
    """PowerShell single-quoted string: literal, one escape only — '' for '.
    No variable expansion, no backtick processing. This is ALWAYS the right
    choice for untrusted payloads."""
    return "'" + s.replace("'", "''") + "'"

def quote_powershell_dq(s: str) -> str:
    """PowerShell double-quoted string: backtick escapes, and $ must be escaped
    or it interpolates. Use only when you WANT interpolation of other parts."""
    out = []
    for ch in s:
        if ch in ('"', '`', '$'):
            out.append('`' + ch)
        else:
            out.append(ch)
    return '"' + ''.join(out) + '"'

def quote_cmd(s: str) -> str:
    """cmd.exe: ^ escapes metacharacters OUTSIDE quotes;
    inside quotes only " matters and there is no escape for it — so avoid.
    Best answer: don't use cmd.exe."""
    if not s or _UNSAFE.search(s):
        return '"' + s.replace('"', '""') + '"'
    return s

def quote_posix(s: str) -> str:
    """shlex.quote is correct for bash/zsh/sh."""
    return shlex.quote(s)

def quote_fish(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"

QUOTERS = {
    "powershell": quote_powershell,
    "pwsh": quote_powershell,
    "cmd": quote_cmd,
    "cmd.exe": quote_cmd,
    "bash": quote_posix,
    "sh": quote_posix,
    "zsh": quote_posix,
    "fish": quote_fish,
}

def powershell_encoded(script: str) -> list[str]:
    """THE BULLETPROOF PATH. -EncodedCommand takes base64 of UTF-16LE script.
    Zero quoting. Zero parser ambiguity. Non-ASCII (Tamil, emoji, anything)
    survives intact. USE THIS for every non-trivial PowerShell invocation."""
    full_script = f"$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); {script}"
    b64 = base64.b64encode(full_script.encode("utf-16-le")).decode("ascii")
    return [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
        b64,
    ]

def pwsh_encoded(script: str) -> list[str]:
    full_script = f"$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); {script}"
    b64 = base64.b64encode(full_script.encode("utf-16-le")).decode("ascii")
    return [
        "pwsh",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
        b64,
    ]

def argv_for(shell: str, script_or_command: str, *, prefer_encoded: bool = True) -> list[str]:
    """Build a shell=False argv for `script_or_command` in the given dialect."""
    s = shell.lower().removesuffix(".exe")
    if s in ("powershell", "pwsh") and prefer_encoded:
        # An explicit nested cmd.exe must not be parsed by the outer PowerShell.
        nested_cmd = re.match(r"^\s*cmd(?:\.exe)?\s+(?:/d\s+)?/c\s+(.+)$", script_or_command, re.IGNORECASE | re.DOTALL)
        if nested_cmd:
            return ["cmd.exe", "/d", "/s", "/c", nested_cmd.group(1)]
        return (powershell_encoded if s == "powershell" else pwsh_encoded)(script_or_command)
    if s in ("bash", "sh", "zsh"):
        return [s, "-c", script_or_command]
    if s in ("cmd", "cmd.exe"):
        return ["cmd.exe", "/d", "/s", "/c", script_or_command]  # /s preserves quoting
    raise ValueError(f"unsupported shell dialect: {shell}")

def youtube_search_url(query: str) -> str:
    return "https://www.youtube.com/results?search_query=" + quote_plus(query, safe="")

def build_url(scheme: str = "https", netloc: str = "", path: str = "", query: dict | None = None, frag: str = "") -> str:
    return urlunsplit((scheme, netloc, path, urlencode(query or {}, quote_via=quote_plus), frag))
