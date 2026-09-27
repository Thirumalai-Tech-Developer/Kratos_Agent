import difflib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import warnings
from typing import Any

logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore", category=DeprecationWarning)

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from kratos_agent.core import git_tools as _git
from kratos_agent.core.approval_mode import approval_gate
from kratos_agent.core.hooks import hook_registry
from kratos_agent.core.memory import memory
from kratos_agent.utils.computer_tools import (
    active_window_info,
    display_info,
    screen_read_text,
    screenshot_capture,
    ui_tree_dump,
)
from kratos_agent.utils.step_tracker import step_tracker

# Reconfigure stdout for UTF-8 on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.debug("Failed to reconfigure stdout/stderr encoding: %s", e)

console = Console(highlight=False)

def format_diff_stat(added: int, removed: int, max_width: int = 8) -> str:
    """Generates a git-style visual diffstat bar (e.g. +12 -4 ████░░)."""
    total = added + removed
    if total == 0:
        return "[dim]no changes[/dim]"
    
    add_blocks = int(round((added / total) * max_width)) if total else 0
    rem_blocks = max_width - add_blocks if (removed > 0 and add_blocks < max_width) else int(round((removed / total) * max_width))
    if added > 0 and add_blocks == 0:
        add_blocks = 1
    if removed > 0 and rem_blocks == 0:
        rem_blocks = 1
    
    bar_parts = []
    if added > 0:
        bar_parts.append(f"[bold green]+{added}[/bold green]")
    if removed > 0:
        bar_parts.append(f"[bold red]-{removed}[/bold red]")
    
    blocks = f"[green]{'█' * add_blocks}[/green][red]{'█' * rem_blocks}[/red]"
    return f"{' '.join(bar_parts)} {blocks}"

def clean_command(cmd_str: str) -> str:
    """Sanitizes terminal command strings by stripping markdown backticks, prefixes, and formatting."""
    cleaned = str(cmd_str).strip()
    backtick_match = re.match(r'^\s*`([^`\n]+)`', cleaned)
    if backtick_match:
        cleaned = backtick_match.group(1).strip()
    else:
        cleaned = re.sub(r'^\s*`+', '', cleaned)
        cleaned = re.sub(r'`+\s*$', '', cleaned)
    cleaned = re.split(r'\n?\s*(?:Tool Inputs:?|```)', cleaned)[0].strip()
    cleaned = re.sub(r'^[a-zA-Z0-9_-]+\s*[:=]\s*\{?', '', cleaned).strip()
    cleaned = re.sub(r'^\{?\s*["\']?(?:command|direct_command|package_name)["\']?\s*[:=]\s*["\']?', '', cleaned).strip()
    cleaned = cleaned.strip()
    return cleaned

def is_persistent_server_command(command: str) -> bool:
    """Accurately checks if a command is starting a persistent background server, avoiding build/install false positives."""
    cmd_lower = command.lower().strip()
    
    # Non-server keywords that must NEVER run in background
    non_server_indicators = [
        "create", "install", "i ", "init", "add", "build", "test", "lint", "check", 
        "setup", "compile", "bundle", "--version", "-v", "--help", "-h", 
        "migrate", "seed", "tsc", "clean", "tailwindcss", "postcss"
    ]
    if any(ind in cmd_lower for ind in non_server_indicators):
        return False
    
    # If the command is a chain (&&, ;, |), check the final command in the chain
    sub_cmds = re.split(r'&&|;|\|', cmd_lower)
    last_cmd = sub_cmds[-1].strip() if sub_cmds else cmd_lower
    
    server_patterns = [
        r'^(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?(?:dev|start|serve|preview)\b',
        r'^(?:npx\s+)?vite(?:\s+dev|\s+preview)?(?:\s+--.*|\s+-\w+)?$',
        r'^(?:python|python3|py)\s+(?:-m\s+http\.server|app\.py|main\.py|server\.py)\b',
        r'^(?:uvicorn|gunicorn|hypercorn)\b',
        r'^(?:nodemon|live-server|http-server)\b',
        r'^node\s+(?:server|app|index|main)\.js\b'
    ]
    return any(re.search(pat, last_cmd) for pat in server_patterns)

def run_terminal_command(command: str = "", argv: list[str] | None = None) -> str:
    """
    Direct Terminal / Shell Access: Executes bash, powershell, or cmd terminal commands directly.
    Shows real-time dynamic single-line status, handles background servers, and tracks completion.
    PREFERRED: pass argv as a list. Only use command as a string when you genuinely need shell features.
    """
    import sys

    from kratos_agent.core.command_lint import lint_command
    from kratos_agent.system.shell.output_parser import normalize_command_output
    from kratos_agent.system.shell.renderer import render_command_argv

    shell_dialect = "powershell" if sys.platform == "win32" else "bash"

    if argv:
        exec_argv = argv
        command = " ".join(argv)
    else:
        command = clean_command(command)
        missing_script = _missing_script_target(command)
        if missing_script:
            return json.dumps({
                "ok": False,
                "code": "SCRIPT_NOT_FOUND",
                "problems": [f"Script target does not exist: {missing_script}"],
                "hint": "Create the script with write_file first, verify it exists, then execute it.",
            }, indent=2)
        # Pre-flight command linter before execution
        lint = lint_command(command, shell_dialect)
        if not lint.ok:
            return json.dumps({
                "ok": False,
                "code": lint.code,
                "problems": lint.problems,
                "suggestion": lint.suggestion,
                "hint": lint.hint,
            }, indent=2)

        exec_argv = render_command_argv(command)

    # Codex-style approval gate + safety blocklist
    if not approval_gate.check_shell(command):
        return f"Shell command blocked by approval mode ({approval_gate.mode.value}): {command}"
    # Claude Code-style pre-tool hook
    hook_registry.fire("pre_tool_call", tool="run_terminal_command", input_str=command)
    step_tracker.start(f"Running: {command}")
    
    # Check if the command is attempting to start a persistent long-running server
    is_server_start = is_persistent_server_command(command)
    
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    try:
        if is_server_start:
            proc = subprocess.Popen(
                exec_argv,
                shell=False,
                creationflags=creationflags,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace"
            )
            time.sleep(0.5)
            poll_res = proc.poll()
            if poll_res is not None and poll_res != 0:
                out, err = proc.communicate(timeout=1)
                step_tracker.fail(f"[bold red]Server failed to start[/bold red] [dim]{command}[/dim]", f"Exit Code: {poll_res}")
                return f"Server failed to start:\n{err or out}\nExit Code: {poll_res}"
            else:
                step_tracker.complete(f"[bold white]Server launched in background[/bold white] [cyan]{command}[/cyan]", f"PID {proc.pid}", success=True)
                memory.record_command(command, 0, f"Server started in background with PID {proc.pid}")
                return f"Server successfully launched in background (PID: {proc.pid}).\nCommand: {command}\nStatus: Active & Listening"

        # Standard command execution with live single-line status updates
        proc = subprocess.Popen(
            exec_argv,
            shell=False,
            creationflags=creationflags,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1
        )
        
        output_lines = []
        try:
            if proc.stdout:
                for line in iter(proc.stdout.readline, ''):
                    clean_line = line.rstrip('\r\n').strip()
                    if clean_line:
                        step_tracker.update(f"Running: {command[:35]} ❯ {clean_line[:45]}")
                    output_lines.append(line)
                proc.stdout.close()
            
            proc.wait(timeout=300)
        except subprocess.TimeoutExpired:
            proc.kill()
            step_tracker.fail("[bold red]Command timed out after 300s[/bold red]", command)
            return f"Error: Command '{command}' timed out after 300 seconds."
        except Exception as stream_err:
            try:
                proc.kill()
            except Exception as e:
                logger.debug("Failed to kill process after stream error: %s", e)
            step_tracker.fail("[bold red]Execution error[/bold red]", str(stream_err))

        raw_text = "".join(output_lines).strip()
        cmd_result = normalize_command_output(raw_text, exit_code=proc.returncode)
        full_output = (cmd_result.stdout or cmd_result.stderr).strip()
        lines = full_output.splitlines()

        # Token-conscious output truncation (Kimi-Code / FCC / Codex pattern)
        output_parts = []
        if len(lines) > 40:
            head = "\n".join(lines[:15])
            tail = "\n".join(lines[-20:])
            omitted = len(lines) - 35
            compact_output = f"{head}\n... [{omitted} lines omitted to reduce token consumption] ...\n{tail}"
            output_parts.append(f"OUTPUT:\n{compact_output}")
        elif full_output:
            output_parts.append(f"OUTPUT:\n{full_output}")
        else:
            output_parts.append("(Command completed with no output)")

        parse_error_patterns = [
            "ParserError",
            "TerminatorExpected",
            "CommandNotFoundException",
            "Traceback (most recent call last)",
            "error :",
            "is not recognized as an internal or external command",
        ]
        parse_error_detected = any(p in full_output for p in parse_error_patterns)
        if parse_error_detected:
            output_parts.append("[PARSE_ERROR DETECTED]: The shell reported a syntax, terminator, or parser error.")
            output_parts.append(
                "[RECOVERY]: Stop retrying the same shell string. Inspect the current UI with computer_visual_diagnose "
                "when the failure is visible, use write_file/edit_file for source code, then re-run a short build/test command."
            )
            output_parts.append(
                "[TOOL_TRACE]: command -> terminal_result -> (computer_visual_diagnose | read_file | write_file/edit_file) -> verify_project -> retry"
            )

        output_parts.append(f"Exit Code: {proc.returncode}")
        
        if proc.returncode == 0:
            step_tracker.complete(f"[bold white]Ran[/bold white] [cyan]{command}[/cyan]", "Exit 0", success=True)
            if any(k in command.lower() for k in ("npm create", "create-vite", "npm install", "npm i ", "yarn add", "pnpm add")):
                output_parts.append("\nNext Step: Proceed immediately to write/edit application code and styling using 'write_file' or 'edit_file'.")
        else:
            step_tracker.complete(f"[bold red]Failed[/bold red] [cyan]{command}[/cyan]", f"Exit Code: {proc.returncode}", success=False)
            if full_output:
                err_sample = "\n".join(full_output.splitlines()[-6:])
                console.print(f"[dim red]{err_sample}[/dim red]")

        # Record in memory
        memory.record_command(command, proc.returncode, full_output)
        final_output = "\n\n".join(output_parts)
        # Claude Code-style post-tool hook
        hook_registry.fire("post_tool_call", tool="run_terminal_command", input_str=command, output_str=final_output[:300])
        return final_output

    except Exception as e:
        step_tracker.fail("[bold red]Execution error[/bold red]", str(e))
        return f"Error executing terminal command: {e}"

def verify_project(project_path: str = ".", timeout: int = 300) -> str:
    """Run deterministic project-level build/typecheck/test checks without shell interpolation."""
    target = Path(project_path).expanduser().resolve()
    if not target.exists() or not target.is_dir():
        return json.dumps({"ok": False, "code": "PROJECT_NOT_FOUND", "project": str(target)}, indent=2)

    commands: list[tuple[str, list[str]]] = []
    package = target / "package.json"
    if package.exists():
        try:
            data = json.loads(package.read_text(encoding="utf-8"))
            scripts = data.get("scripts", {}) if isinstance(data, dict) else {}
        except Exception as exc:
            return json.dumps({"ok": False, "code": "INVALID_PACKAGE_JSON", "error": str(exc)}, indent=2)
        npm = shutil.which("npm.cmd") or shutil.which("npm") or "npm"
        if "typecheck" in scripts:
            commands.append(("npm run typecheck", [npm, "run", "typecheck"]))
        elif (target / "tsconfig.json").exists():
            npx = shutil.which("npx.cmd") or shutil.which("npx")
            if npx:
                commands.append(("npx tsc --noEmit", [npx, "tsc", "--noEmit"]))
        if "lint" in scripts:
            commands.append(("npm run lint", [npm, "run", "lint"]))
        if "build" in scripts:
            commands.append(("npm run build", [npm, "run", "build"]))
        if "test" in scripts:
            commands.append(("npm test", [npm, "test"]))

    if not commands:
        pyproject = target / "pyproject.toml"
        if pyproject.exists():
            python = shutil.which("python") or shutil.which("python3") or "python"
            commands.append(("python -m compileall -q .", [python, "-m", "compileall", "-q", "."]))
            if (target / "tests").exists():
                pytest_bin = shutil.which("pytest")
                if pytest_bin:
                    commands.append(("pytest -q", [pytest_bin, "-q"]))

    if not commands:
        return json.dumps({
            "ok": False,
            "code": "NO_VERIFICATION_SCRIPT",
            "project": str(target),
            "hint": "No deterministic build/test entry point was discovered. Inspect the project manifest first.",
        }, indent=2)

    report = []
    all_ok = True
    for label, argv in commands:
        started = time.monotonic()
        try:
            proc = subprocess.run(
                argv,
                cwd=str(target),
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env={**os.environ, "CI": "1", "NO_COLOR": "1"},
            )
            out = (proc.stdout or proc.stderr or "").strip()
            ok = proc.returncode == 0
            all_ok = all_ok and ok
            report.append({
                "command": label,
                "argv": argv,
                "ok": ok,
                "exit_code": proc.returncode,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "output": out[-5000:],
            })
            if not ok:
                break
        except subprocess.TimeoutExpired as exc:
            all_ok = False
            report.append({
                "command": label,
                "argv": argv,
                "ok": False,
                "code": "TIMEOUT",
                "duration_ms": int((time.monotonic() - started) * 1000),
                "output": str(exc),
            })
            break
        except Exception as exc:
            all_ok = False
            report.append({"command": label, "argv": argv, "ok": False, "code": type(exc).__name__, "output": str(exc)})
            break

    return json.dumps({
        "ok": all_ok,
        "code": "VERIFIED" if all_ok else "VERIFICATION_FAILED",
        "project": str(target),
        "checks": report,
        "recovery_tools": [] if all_ok else ["read_file", "write_file", "edit_file", "run_terminal_command", "computer_visual_diagnose"],
    }, indent=2)


def computer_visual_diagnose(include_ocr: bool = True) -> str:
    """Build a fresh multimodal desktop diagnostic bundle for visual problem solving."""
    result: dict[str, Any] = {"ok": True, "timestamp": time.time()}
    try:
        result["active_window"] = json.loads(active_window_info())
    except Exception as exc:
        result["active_window_error"] = str(exc)
    try:
        result["display"] = json.loads(display_info())
    except Exception as exc:
        result["display_error"] = str(exc)
    try:
        result["screenshot"] = json.loads(screenshot_capture(downscale=0))
    except Exception as exc:
        result["screenshot_error"] = str(exc)
    if include_ocr:
        try:
            text_out = screen_read_text()
            result["screen_text"] = text_out[:6000]
        except Exception as exc:
            result["ocr_error"] = str(exc)
    try:
        result["ui_tree"] = json.loads(ui_tree_dump(max_nodes=200))
    except Exception as exc:
        result["ui_tree_error"] = str(exc)
    return json.dumps(result, ensure_ascii=False, indent=2)


def clean_file_path(fp_str: str) -> str:
    """Cleans file paths from raw string prefixes, URL schemes, and quote artifacts, redirecting any scratch paths into the active workspace."""
    cleaned = str(fp_str).strip()
    cleaned = re.sub(r'^[rfbRFB]?#*["\']?', '', cleaned)
    cleaned = re.sub(r'["\']?#*$', '', cleaned)
    cleaned = cleaned.strip('"\' \t\n')
    if cleaned.startswith("file:///"):
        cleaned = cleaned[8:]
    elif cleaned.startswith("file://"):
        cleaned = cleaned[7:]

    # Normalize slashes
    norm_path = cleaned.replace("\\", "/")

    # Strip external scratch paths and anchor into current directory
    if "antigravity-cli" in norm_path.lower() or ".gemini" in norm_path.lower() or "/scratch/" in norm_path.lower():
        parts = re.split(r'/scratch/', norm_path, flags=re.IGNORECASE)
        if len(parts) > 1:
            sub = parts[1].lstrip("/")
            sub_parts = [p for p in sub.split("/") if p]
            cleaned = "/".join(sub_parts[1:]) if len(sub_parts) > 1 else (sub_parts[0] if sub_parts else "script.py")
        else:
            cleaned = norm_path.lstrip("/")
    else:
        cleaned = norm_path

    return cleaned.lstrip("/")

def _missing_script_target(command: str) -> str | None:
    """Detect an explicit PowerShell -File target that does not exist yet."""
    if sys.platform != "win32":
        return None
    match = re.search(r"""(?i)(?:^|\s)-(?:file|f)\s+(?:"([^"]+)"|'([^']+)'|([^\s]+))""", command)
    if not match:
        return None
    target = next((group for group in match.groups() if group), "").strip()
    if not target:
        return None
    target_path = Path(target).expanduser()
    if not target_path.is_absolute():
        target_path = Path.cwd() / target_path
    return str(target_path) if not target_path.exists() else None


def write_file(file_path: str, content: str) -> str:
    """
    Writes text or code directly to a file on disk in the workspace with UTF-8 encoding.
    Tracks lines added/removed with visual git-stat feedback and token-optimized return values.
    """
    file_path = clean_file_path(file_path)
    # Codex SUGGEST mode blocks all file writes
    if not approval_gate.check_write(file_path):
        return f"File write blocked by approval mode ({approval_gate.mode.value}): {file_path}"
    hook_registry.fire("pre_tool_call", tool="write_file", input_str=file_path)
    step_tracker.start(f"Writing {file_path}...")
    try:
        if not file_path or file_path in ("r#", "r", "#"):
            file_path = "script.py"
        content_str = str(content)
        content_str = re.sub(r'^\s*```[a-zA-Z0-9_-]*\s*\n?', '', content_str)
        content_str = re.sub(r'\n?\s*```\s*$', '', content_str)
        content_str = re.sub(r'^\s*`+', '', content_str)
        content_str = re.sub(r'`+\s*$', '', content_str)

        p = Path(file_path)
        existed = p.exists()
        old_content = ""
        if existed:
            try:
                old_content = p.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                logger.debug("Failed to read existing content for %s: %s", p, e)

        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content_str, encoding="utf-8")
        new_lines = content_str.splitlines()
        num_lines = len(new_lines)

        if not existed:
            stat_bar = f"[bold green]+{num_lines} lines[/bold green] [green]{'█' * min(10, max(1, num_lines // 15))}[/green]"
            step_tracker.complete(f"[bold white]Created[/bold white] [cyan]{file_path}[/cyan]", stat_bar, success=True)
            try:
                from kratos_agent.tui.highlighter import print_code_dialog
                print_code_dialog(content_str, file_path=file_path, action="CREATED FILE", console=console)
            except Exception as exc:
                logger.debug("Code highlight display error: %s", exc)
            return f"Successfully created '{file_path}' (+{num_lines} lines)."
        else:
            diff = list(difflib.unified_diff(old_content.splitlines(), new_lines, lineterm=""))
            added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
            removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
            stat_bar = format_diff_stat(added, removed)
            step_tracker.complete(f"[bold white]Wrote[/bold white] [cyan]{file_path}[/cyan]", stat_bar, success=True)
            try:
                from kratos_agent.tui.highlighter import print_code_dialog
                print_code_dialog(content_str, file_path=file_path, action="UPDATED FILE", console=console)
            except Exception as exc:
                logger.debug("Code highlight display error: %s", exc)
            return f"Successfully updated '{file_path}' (+{added}, -{removed} lines)."
    except Exception as e:
        step_tracker.fail(f"[bold red]Failed writing[/bold red] [cyan]{file_path}[/cyan]", str(e))
        return f"Error writing file '{file_path}': {e}"

def read_file(file_path: str) -> str:
    """
    Reads the content of a file from the workspace.
    """
    file_path = clean_file_path(file_path)
    step_tracker.start(f"Reading {file_path}...")
    try:
        p = Path(file_path)
        if not p.exists():
            step_tracker.fail("[bold red]File not found[/bold red]", file_path)
            return f"Error: File '{file_path}' does not exist."
        content = p.read_text(encoding="utf-8", errors="replace")
        num_lines = len(content.splitlines())
        step_tracker.complete(f"[bold white]Read[/bold white] [cyan]{file_path}[/cyan]", f"{num_lines} lines", success=True)
        return content
    except Exception as e:
        step_tracker.fail(f"[bold red]Failed reading[/bold red] [cyan]{file_path}[/cyan]", str(e))
        return f"Error reading file '{file_path}': {e}"

def edit_file(file_path: str, target_text: str, replacement_text: str) -> str:
    """
    Surgical search-and-replace editor: Replaces exact target text with replacement text in a file.
    Preserves all other code, comments, and structure without rewriting entire files.
    Calculates unified diffstat and renders visual change feedback.
    """
    file_path = clean_file_path(file_path)
    # Codex SUGGEST mode blocks all file writes
    if not approval_gate.check_write(file_path):
        return f"File edit blocked by approval mode ({approval_gate.mode.value}): {file_path}"
    hook_registry.fire("pre_tool_call", tool="edit_file", input_str=file_path)
    step_tracker.start(f"Editing {file_path}...")
    try:
        p = Path(file_path)
        if not p.exists():
            step_tracker.fail("[bold red]File not found[/bold red]", file_path)
            return f"Error: File '{file_path}' does not exist. Use 'write_file' to create new files."
        
        current_content = p.read_text(encoding="utf-8", errors="replace")
        
        # Normalize target text and check match
        if target_text not in current_content:
            target_norm = target_text.replace("\r\n", "\n")
            content_norm = current_content.replace("\r\n", "\n")
            if target_norm not in content_norm:
                step_tracker.fail(f"[bold red]Target text not found[/bold red] in [cyan]{file_path}[/cyan]")
                return (
                    f"Error: Target text not found in '{file_path}'. "
                    f"Ensure target_text matches exact existing lines including whitespace."
                )
            new_content = content_norm.replace(target_norm, replacement_text, 1)
        else:
            new_content = current_content.replace(target_text, replacement_text, 1)

        # Compute diffstat
        diff = list(difflib.unified_diff(current_content.splitlines(), new_content.splitlines(), lineterm=""))
        added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
        removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
        stat_bar = format_diff_stat(added, removed)

        p.write_text(new_content, encoding="utf-8")
        step_tracker.complete(f"[bold white]Edited[/bold white] [cyan]{file_path}[/cyan]", stat_bar, success=True)

        # Display compact syntax-highlighted diff preview in terminal if <= 15 diff lines
        if diff and len(diff) <= 15:
            diff_text = "\n".join(diff)
            console.print(Panel(
                Syntax(diff_text, "diff", theme="monokai", line_numbers=False),
                title=f"[dim]git diff {file_path}[/dim]",
                border_style="dim",
                padding=(0, 1)
            ))

        return f"Successfully updated '{file_path}' (+{added}, -{removed} lines). Surgical edit applied."
    except Exception as e:
        step_tracker.fail(f"[bold red]Failed editing[/bold red] [cyan]{file_path}[/cyan]", str(e))
        return f"Error editing file '{file_path}': {e}"

def list_directory(directory_path: str = ".", max_depth: int = 2) -> str:
    """
    Explores and lists files and folders in a workspace directory with depth limit.
    """
    clean_dir = clean_file_path(directory_path)
    step_tracker.start(f"Listing directory {clean_dir}...")
    try:
        target = Path(clean_dir)
        if not target.exists():
            step_tracker.fail("[bold red]Directory not found[/bold red]", clean_dir)
            return f"Error: Directory '{directory_path}' does not exist."
        if not target.is_dir():
            step_tracker.fail("[bold red]Not a directory[/bold red]", clean_dir)
            return f"Error: '{directory_path}' is a file, not a directory."

        ignored = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", ".next", ".turbo"}
        tree_lines = [f"📁 Directory listing for '{directory_path}':"]
        
        base_depth = len(target.resolve().parts)
        item_count = 0
        for root, dirs, files in os.walk(target):
            curr_path = Path(root)
            depth = len(curr_path.resolve().parts) - base_depth
            if depth > max_depth:
                dirs.clear()
                continue
            
            dirs[:] = [d for d in dirs if d not in ignored]
            
            indent = "  " * depth
            rel_dir = curr_path.relative_to(target)
            if depth > 0:
                tree_lines.append(f"{indent}📂 {rel_dir.name}/")
                item_count += 1
            
            for f in sorted(files):
                if depth + 1 <= max_depth:
                    file_indent = "  " * (depth + 1)
                    tree_lines.append(f"{file_indent}📄 {f}")
                    item_count += 1

        output = "\n".join(tree_lines)
        step_tracker.complete(f"[bold white]Listed directory[/bold white] [cyan]{directory_path}[/cyan]", f"{item_count} items", success=True)
        return output
    except Exception as e:
        step_tracker.fail(f"[bold red]Failed listing[/bold red] [cyan]{directory_path}[/cyan]", str(e))
        return f"Error listing directory '{directory_path}': {e}"

def grep_search(query: str, directory_path: str = ".", is_regex: bool = False) -> str:
    """
    Fast regex and text code search across workspace source files.
    """
    step_tracker.start(f"Searching code for '{query}'...")
    try:
        target = Path(clean_file_path(directory_path))
        if not target.exists():
            step_tracker.fail("[bold red]Path not found[/bold red]", directory_path)
            return f"Error: Path '{directory_path}' does not exist."

        ignored = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", ".kratos/sessions"}
        matches = []
        pattern = re.compile(query, re.IGNORECASE) if is_regex else None

        for root, dirs, files in os.walk(target):
            dirs[:] = [d for d in dirs if d not in ignored]
            for f in files:
                if f.endswith((".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".json", ".md", ".toml", ".yaml", ".yml", ".env")):
                    file_p = Path(root) / f
                    try:
                        lines = file_p.read_text(encoding="utf-8", errors="replace").splitlines()
                        for line_no, line in enumerate(lines, 1):
                            matched = (pattern.search(line) is not None) if pattern else (query.lower() in line.lower())
                            if matched:
                                rel_path = file_p.relative_to(Path.cwd()) if file_p.is_relative_to(Path.cwd()) else file_p
                                matches.append(f"{rel_path}:{line_no}: {line.strip()[:140]}")
                                if len(matches) >= 40:
                                    break
                    except Exception as e:
                        logger.debug("Failed reading file during grep: %s", e)
                if len(matches) >= 40:
                    break
            if len(matches) >= 40:
                break

        if not matches:
            step_tracker.complete(f"[bold white]Grep search[/bold white] [cyan]'{query}'[/cyan]", "0 matches", success=True)
            return f"No matches found for '{query}' in '{directory_path}'."

        res = f"Found {len(matches)} match(es) for '{query}':\n" + "\n".join(matches)
        step_tracker.complete(f"[bold white]Grep search[/bold white] [cyan]'{query}'[/cyan]", f"{len(matches)} matches", success=True)
        return res
    except Exception as e:
        step_tracker.fail("[bold red]Grep search error[/bold red]", str(e))
        return f"Error during grep search: {e}"

def fetch_url(url: str) -> str:
    """
    Fetches web documentation or web page text content for real-time libraries, APIs, or research.
    """
    step_tracker.start(f"Fetching {url}...")
    try:
        import urllib.request
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw_html = resp.read().decode("utf-8", errors="replace")
            clean_html = re.sub(r'<script.*?</script>', '', raw_html, flags=re.DOTALL | re.IGNORECASE)
            clean_html = re.sub(r'<style.*?</style>', '', clean_html, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<[^>]+>', ' ', clean_html)
            text = re.sub(r'\s+', ' ', text).strip()
            
            summary = text[:2500] + ("..." if len(text) > 2500 else "")
            step_tracker.complete(f"[bold white]Fetched URL[/bold white] [cyan]{url}[/cyan]", f"{len(text)} chars", success=True)
            return f"Content of {url}:\n\n{summary}"
    except Exception as e:
        step_tracker.fail(f"[bold red]Failed fetching URL[/bold red] [cyan]{url}[/cyan]", str(e))
        return f"Error fetching URL '{url}': {e}"

def google_search(query: str) -> str:
    """
    Performs a real-time web search using the Kratos Search Fabric with multi-engine
    aggregation, deduplication, ranking, and citations.
    """
    step_tracker.start(f"Searching web for '{query}'...")
    try:
        import asyncio

        from kratos_agent.search import (
            format_search_results_with_citations,
            get_search_router,
        )

        router = get_search_router()
        from kratos_agent.utils.async_runner import run_coroutine
        resp = run_coroutine(router.search(query), timeout=15.0)

        if resp and resp.results:
            formatted = format_search_results_with_citations(resp.results)
            step_tracker.complete(f"[bold white]Web search[/bold white] [cyan]'{query}'[/cyan]", f"{len(resp.results)} results ({resp.provider})", success=True)
            return formatted

        step_tracker.complete(f"[bold white]Web search[/bold white] [cyan]'{query}'[/cyan]", "0 results", success=True)
        return "No search results found for query."
    except Exception as e:
        step_tracker.fail("[bold red]Web search error[/bold red]", str(e))
        return f"Search error: {e}"


def web_search(query: str) -> str:
    """Alias for google_search routed through Kratos Search Fabric."""
    return google_search(query)


# --- Auto-generated tool: calculate_expression ---
def calculate_expression(expression: str) -> str:
    """Evaluates a mathematical expression safely."""
    step_tracker.start(f"Evaluating math: {expression}...")
    try:
        import ast
        import operator
        ops = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.Pow: operator.pow
        }
        def ev(n):
            if isinstance(n, ast.Constant):
                return n.value
            if isinstance(n, ast.BinOp):
                return ops[type(n.op)](ev(n.left), ev(n.right))
            raise TypeError("Unsupported")
        res = str(ev(ast.parse(expression, mode="eval").body))
        step_tracker.complete(f"[bold white]Math evaluated[/bold white] [cyan]{expression} = {res}[/cyan]", success=True)
        return res
    except Exception as e:
        step_tracker.fail("[bold red]Math evaluation error[/bold red]", str(e))
        return f"Math error: {e}"


# ──────────────────────────────────────────────────────────
# Git Tool Wrappers (Claude Code / Codex / Kimi git integration)
# ──────────────────────────────────────────────────────────

def git_status() -> str:
    """Shows current git repository status: staged, unstaged, and untracked file changes."""
    step_tracker.start("Checking git status...")
    result = _git.get_git_status()
    step_tracker.complete("[bold white]Git status[/bold white]", "", success=True)
    return result


def git_diff(staged: bool = False) -> str:
    """Shows the current git diff. Set staged=True to see what would be committed."""
    step_tracker.start("Getting git diff...")
    result = _git.get_git_diff(staged=staged)
    step_tracker.complete("[bold white]Git diff[/bold white]", "", success=True)
    return result


def git_commit(message: str = "") -> str:
    """Stages all changes and creates a git commit. Auto-generates Conventional Commits message if none given."""
    if not approval_gate.check_shell(f"git commit -m '{message}'"):
        return f"git commit blocked by approval mode ({approval_gate.mode.value})."
    step_tracker.start(f"Committing: {message or 'auto-message'}...")
    result = _git.create_commit(message=message)
    step_tracker.complete("[bold white]Git commit[/bold white]", "", success=True)
    return result


def git_push(branch: str = "") -> str:
    """Pushes the current branch to the remote repository (origin)."""
    if not approval_gate.check_shell(f"git push origin {branch or 'HEAD'}"):
        return f"git push blocked by approval mode ({approval_gate.mode.value})."
    step_tracker.start("Pushing to remote...")
    result = _git.git_push(branch=branch)
    step_tracker.complete("[bold white]Git push[/bold white]", "", success=True)
    return result


def git_create_pr(title: str = "", body: str = "", base: str = "main") -> str:
    """Creates a GitHub Pull Request. Pushes branch first. Requires gh CLI to be installed."""
    if not approval_gate.check_shell("gh pr create"):
        return f"PR creation blocked by approval mode ({approval_gate.mode.value})."
    step_tracker.start("Creating Pull Request...")
    result = _git.create_pr(title=title, body=body, base=base)
    step_tracker.complete("[bold white]Pull Request[/bold white]", "", success=True)
    return result


# ──────────────────────────────────────────────────────────
# Cognitive Memory Tools (4-Tier Architecture)
# ──────────────────────────────────────────────────────────

def save_memory(memory_type: str, key: str, content: str) -> str:
    """
    Stores an item into cognitive memory across one of the 4 cognitive layers:
      - 'working': Current task objectives, active scratchpad notes, temporary variables
      - 'episodic': Specific experiences, past tool outcomes, bug retrospectives, lessons learned
      - 'semantic': Persistent facts, project conventions, architectural decisions, user preferences
      - 'procedural': "How-to" workflows, skills, build recipes, verification protocols
    """
    step_tracker.start(f"Saving {memory_type} memory: {key}...")
    try:
        record = memory.save_cognitive_memory(memory_type=memory_type, key=key, content=content)
        step_tracker.complete(f"[bold white]Saved Memory[/bold white] [cyan][{record['memory_type'].upper()}] {key}[/cyan]", success=True)
        return f"Successfully saved {record['memory_type']} memory '{key}' (ID: {record['id']})."
    except Exception as e:
        step_tracker.fail("Failed to save memory", str(e))
        return f"Error saving memory: {e}"


def read_memory(memory_type: str = "", key: str = "", query: str = "") -> str:
    """
    Recalls items from cognitive memory by type ('working', 'episodic', 'semantic', 'procedural'), key, or search query.
    If all parameters are empty, returns the full active cognitive memory summary and prompt context.
    """
    step_tracker.start(f"Recalling memory ({memory_type or 'all'})...")
    try:
        m_type = memory_type.strip() if memory_type.strip() else None
        k = key.strip() if key.strip() else None
        q = query.strip() if query.strip() else None

        records = memory.recall_cognitive_memory(memory_type=m_type, key=k, query=q, limit=15)
        if not records:
            step_tracker.complete("[bold white]Memory query[/bold white]", "No records found", success=True)
            return f"No memory records found matching criteria (type={memory_type}, key={key}, query={query})."

        lines = [f"Found {len(records)} cognitive memory record(s):"]
        for r in records:
            lines.append(f"• [{r.get('memory_type', '').upper()}] {r.get('key')}: {r.get('content')} (Updated: {r.get('updated_at')})")

        res = "\n".join(lines)
        step_tracker.complete(f"[bold white]Recalled {len(records)} memories[/bold white]", "", success=True)
        return res
    except Exception as e:
        step_tracker.fail("Failed to read memory", str(e))
        return f"Error reading memory: {e}"


def clear_memory(memory_type: str = "") -> str:
    """
    Clears cognitive memory records. If memory_type is specified ('working', 'episodic', 'semantic', 'procedural'),
    only that layer is cleared. If empty or 'working', clears the active session working scratchpad.
    """
    step_tracker.start(f"Clearing memory ({memory_type or 'working'})...")
    try:
        m_type = memory_type.strip() if memory_type.strip() else None
        cleared = memory.clear_cognitive_memory(memory_type=m_type)
        step_tracker.complete("[bold white]Cleared memory[/bold white]", f"Type: {memory_type or 'all'}", success=True)
        return f"Cleared cognitive memory layer '{memory_type or 'all'}'."
    except Exception as e:
        step_tracker.fail("Failed to clear memory", str(e))
        return f"Error clearing memory: {e}"


def optimize_memory(min_confidence: float = 0.15) -> str:
    """
    Performs full memory maintenance and optimization across all memory layers:
      - Applies time-based decay policies
      - Prunes low-confidence, stale, and expired records
      - Deduplicates facts and merges redundant memory entries
      - Trims oversized tool and command logs in sessions
      - Runs VACUUM on the database to reclaim disk space
    """
    step_tracker.start("Optimizing memory systems...")
    try:
        from kratos_agent.memory.maintenance import get_memory_optimizer
        report = get_memory_optimizer().run_maintenance(min_confidence=min_confidence)
        stats_str = (
            f"Memory optimization completed in {report.duration_ms:.1f}ms:\n"
            f"• Decayed records: {report.decayed_count}\n"
            f"• Pruned stale records: {report.pruned_records_count}\n"
            f"• Deduplicated facts: {report.deduplicated_count}\n"
            f"• Cognitive records cleaned: {report.cognitive_records_pruned}\n"
            f"• Session logs trimmed: {report.tool_outputs_trimmed}\n"
            f"• Database reclaimed: {report.db_reclaimed_bytes:,} bytes\n"
            f"• Active retained memories: {report.retained_records_count}"
        )
        step_tracker.complete("[bold white]Memory Optimized[/bold white]", f"{report.retained_records_count} records", success=True)
        return stats_str
    except Exception as e:
        step_tracker.fail("Failed to optimize memory", str(e))
        return f"Error optimizing memory: {e}"


# ──────────────────────────────────────────────────────────
# Subagent Orchestration Tool
# ──────────────────────────────────────────────────────────

_subagent_runner = None


def set_subagent_runner(runner) -> None:
    """Sets the subagent execution runner callback (typically runtime.subagents.run)."""
    global _subagent_runner
    _subagent_runner = runner


def spawn_subagent(role: str, task: str) -> str:
    """
    Spawns an isolated specialized subagent to perform focused work without polluting the main context.
    Standard roles:
      - 'code_reviewer': Reviews code, checks best practices, catches edge cases and potential bugs.
      - 'security_auditor': Scans code/deps for vulnerabilities, credential leaks, and unsafe patterns.
      - 'researcher': Explores workspace files, documentation, architecture, or web references.
      - 'debugger': Traces root causes, analyzes stack traces, and reproduces edge cases.
      - 'architect': Designs component boundaries, API schemas, and state flows.
      - 'tester': Formulates unit tests, edge case assertions, and verification checklists.
    """
    clean_role = (role or "researcher").strip()
    clean_task = (task or "").strip()
    if not clean_task:
        return "Error: Subagent task description cannot be empty."

    step_tracker.start(f"Delegating to {clean_role} subagent: {clean_task[:50]}...")
    if _subagent_runner is None:
        step_tracker.complete(f"[bold white]Subagent ({clean_role})[/bold white]", "Runner unconfigured", success=True)
        return f"[subagent-{clean_role}] Subagent runner not active in current session. Task: {clean_task}"

    try:
        res = _subagent_runner(clean_role, clean_task)
        if hasattr(res, "summary"):
            output = res.summary
            if getattr(res, "error", None):
                output = f"[subagent error: {res.error}]\n{output}"
        else:
            output = str(res)
        step_tracker.complete(f"[bold white]Subagent ({clean_role})[/bold white]", "Report ready", success=True)
        return f"[Subagent '{clean_role}' Report]:\n{output}"
    except Exception as e:
        step_tracker.fail(f"Subagent ({clean_role}) failed", str(e))
        return f"Error executing subagent '{clean_role}': {e}"


_parallel_subagent_runner = None


def set_parallel_subagent_runner(runner) -> None:
    """Sets the parallel subagent execution callback (typically runtime.subagents.run_multi_parallel)."""
    global _parallel_subagent_runner
    _parallel_subagent_runner = runner


def spawn_parallel_subagents(subagents: list[dict[str, str]]) -> str:
    """Spawns multiple isolated specialized subagents concurrently in parallel threads.

    Each subagent executes its focused task simultaneously, saving significant time.
    Standard roles: 'code_reviewer', 'security_auditor', 'researcher', 'debugger', 'architect', 'tester'.

    Args:
        subagents: List of subagent specs: [{'role': 'code_reviewer', 'task': '...'}, {'role': 'tester', 'task': '...'}]

    Returns:
        Consolidated markdown report containing findings from all completed subagents.
    """
    if not subagents or not isinstance(subagents, list):
        return "Error: subagents parameter must be a non-empty list of {'role': ..., 'task': ...} objects."

    valid_specs = []
    for s in subagents:
        if isinstance(s, dict) and s.get("task"):
            valid_specs.append({
                "role": (s.get("role") or "researcher").strip(),
                "task": s.get("task", "").strip(),
            })

    if not valid_specs:
        return "Error: No valid subagent tasks found in arguments."

    t0 = time.monotonic()

    # Use parallel runner if configured, else fall back to ThreadPoolExecutor calling _subagent_runner
    if _parallel_subagent_runner is not None:
        results = _parallel_subagent_runner(valid_specs)
    elif _subagent_runner is not None:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(len(valid_specs), 6)) as pool:
            futures = [pool.submit(_subagent_runner, s["role"], s["task"]) for s in valid_specs]
            results = [f.result() for f in futures]
    else:
        return f"[spawn_parallel_subagents] Subagent runner not active in current session. Planned tasks: {len(valid_specs)}"

    elapsed_s = round(time.monotonic() - t0, 2)
    reports = [f"### ⚡ Parallel Subagent Execution Report ({len(valid_specs)} subagents completed in {elapsed_s}s)\n"]

    for spec, res in zip(valid_specs, results):
        role = spec["role"]
        task = spec["task"]
        if hasattr(res, "summary"):
            output = res.summary
            if getattr(res, "error", None):
                output = f"[error: {res.error}]\n{output}"
        else:
            output = str(res)
        reports.append(f"#### 🤖 Subagent: `{role}` (Task: {task[:60]})\n{output}\n")

    return "\n".join(reports)



# ──────────────────────────────────────────────────────────
# Skill Playbook Tools
# ──────────────────────────────────────────────────────────

def list_skills(filter_tag: str = "") -> str:
    """
    Lists available skill playbooks and expert guidelines installed in Kratos.
    Optionally filters by keyword or tag (e.g. 'design', 'security', 'api', 'react').
    """
    from kratos_agent.core.skills import skill_manager

    step_tracker.start("Listing skills...")
    try:
        unique_skills = list({str(s.path): s for s in skill_manager.skills.values()}.values())
        filt = (filter_tag or "").strip().lower()
        if filt:
            unique_skills = [
                s for s in unique_skills
                if filt in s.name.lower() or filt in s.description.lower() or any(filt in t.lower() for t in s.tags)
            ]
        if not unique_skills:
            step_tracker.complete("[bold white]Skills listed[/bold white]", "None found", success=True)
            return f"No skills found matching filter '{filter_tag}'."

        lines = [f"Found {len(unique_skills)} skill(s):"]
        for s in unique_skills[:35]:
            desc = s.description[:80] + "…" if len(s.description) > 80 else s.description
            tags_str = f" [{', '.join(s.tags[:3])}]" if s.tags else ""
            lines.append(f"• `{s.name}`{tags_str}: {desc}")
        if len(unique_skills) > 35:
            lines.append(f"... and {len(unique_skills) - 35} more skills. Filter by tag to narrow down.")

        step_tracker.complete("[bold white]Skills listed[/bold white]", f"Total: {len(unique_skills)}", success=True)
        return "\n".join(lines)
    except Exception as e:
        step_tracker.fail("Failed to list skills", str(e))
        return f"Error listing skills: {e}"


def read_skill(skill_name: str) -> str:
    """
    Reads and returns the complete guide and best practices for an installed skill
    (e.g. 'frontend-design', 'theme-factory', 'api-sec', 'canvas-design').
    """
    from kratos_agent.core.skills import skill_manager

    s_name = (skill_name or "").strip().lower()
    if not s_name:
        return "Error: Please specify a skill_name. Use list_skills to view available skills."

    step_tracker.start(f"Reading skill: {s_name}...")
    try:
        skill = skill_manager.skills.get(s_name)
        if not skill:
            # Fallback search by substring
            for k, v in skill_manager.skills.items():
                if s_name in k or k in s_name:
                    skill = v
                    break

        if not skill:
            step_tracker.fail(f"Skill '{s_name}' not found")
            return f"Skill '{skill_name}' not found. Call `list_skills()` to see available playbooks."

        content = skill.content
        if not content and (skill.path / "SKILL.md").exists():
            content = (skill.path / "SKILL.md").read_text(encoding="utf-8", errors="replace")

        step_tracker.complete("[bold white]Skill Loaded[/bold white]", f"[cyan]{skill.name}[/cyan]", success=True)
        return f"# SKILL PLAYBOOK: {skill.name}\n\nDescription: {skill.description}\nTags: {', '.join(skill.tags)}\n\n{content}"
    except Exception as e:
        step_tracker.fail(f"Failed to read skill '{skill_name}'", str(e))
        return f"Error reading skill '{skill_name}': {e}"


# ──────────────────────────────────────────────────────────
# Dynamic Todo & Plan Mode Tools (DeepSeek Harness / Claude Code)
# ──────────────────────────────────────────────────────────

_todo_handler = None
_plan_mode_handler = None


def set_todo_handler(handler) -> None:
    """Sets callback for dynamic todo list updates."""
    global _todo_handler
    _todo_handler = handler


def set_plan_mode_handler(handler) -> None:
    """Sets callback for exiting plan mode."""
    global _plan_mode_handler
    _plan_mode_handler = handler


def todo_write(todos) -> str:
    """
    Updates the agent's dynamic todo/task list with a whole-list replacement.
    Accepts a list of dicts with 'content' and 'status' ('pending', 'in_progress', 'completed').
    Also accepts JSON-encoded strings if passed by the LLM.
    """
    global _todo_handler
    step_tracker.start("Updating todo list...")
    try:
        items = todos
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                items = [{"content": str(items).strip(), "status": "pending"}]

        if isinstance(items, dict):
            if "todos" in items:
                items = items["todos"]
            else:
                items = [items]

        if not isinstance(items, list):
            items = [{"content": str(items).strip(), "status": "pending"}]

        normalized = []
        for it in items:
            if isinstance(it, dict):
                content = str(it.get("content") or it.get("title") or it.get("task") or "Untitled task").strip()
                status = str(it.get("status") or "pending").strip().lower()
            elif isinstance(it, str):
                content = it.strip()
                status = "pending"
            else:
                content = str(it)
                status = "pending"

            if status not in ("pending", "in_progress", "completed", "running"):
                status = "pending"
            if status == "running":
                status = "in_progress"
            normalized.append({"content": content, "status": status})

        completed_count = sum(1 for t in normalized if t["status"] == "completed")
        in_progress_count = sum(1 for t in normalized if t["status"] == "in_progress")
        pending_count = sum(1 for t in normalized if t["status"] == "pending")

        if _todo_handler:
            try:
                _todo_handler(normalized)
            except Exception as handler_err:
                step_tracker.fail("Todo handler failed", str(handler_err))

        summary = f"Todo list updated: {len(normalized)} item(s) ({completed_count} completed, {in_progress_count} in_progress, {pending_count} pending)."
        step_tracker.complete("[bold white]Todos Updated[/bold white]", f"{completed_count}/{len(normalized)} done", success=True)
        return summary
    except Exception as e:
        step_tracker.fail("Failed to update todo list", str(e))
        return f"Error updating todo list: {e}"


def exit_plan_mode(plan: str) -> str:
    """
    Exits Plan Mode and presents the complete implementation plan for user review.
    The plan must be formatted as markdown starting with '#'.
    """
    global _plan_mode_handler
    step_tracker.start("Submitting plan & exiting Plan Mode...")
    try:
        plan_str = str(plan or "").strip()
        if not plan_str:
            step_tracker.fail("Plan submission empty")
            return "Error: Plan content cannot be empty. Please provide a complete markdown plan starting with '#'."

        if not plan_str.startswith("#"):
            plan_str = f"# Implementation Plan\n\n{plan_str}"

        if _plan_mode_handler:
            try:
                _plan_mode_handler(plan_str)
            except Exception as handler_err:
                step_tracker.fail("Plan mode handler failed", str(handler_err))

        step_tracker.complete("[bold white]Plan Mode Exited[/bold white]", "Plan presented for review", success=True)
        return "Plan submitted successfully. Plan Mode is now exited. Proceeding to execution upon user confirmation."
    except Exception as e:
        step_tracker.fail("Failed to exit Plan Mode", str(e))
        return f"Error exiting Plan Mode: {e}"

# --- Auto-generated tool: role_play_answer ---
def role_play_answer(query: str, role: str, context: str = '', tone: str = 'neutral', max_length: int = 300, include_actions: bool = False) -> str:
    '''Generate a deterministic in-character role-play answer.'''
    if not isinstance(query, str) or not query.strip():
        raise ValueError('query must be a non-empty string')
    if not isinstance(role, str) or not role.strip():
        raise ValueError('role must be a non-empty string')
    if not isinstance(max_length, int) or max_length < 1:
        raise ValueError('max_length must be a positive integer')
    role_clean = role.strip()
    query_clean = query.strip()
    tone_clean = tone.strip().lower() if isinstance(tone, str) and tone.strip() else 'neutral'
    tone_map = {
        'neutral': 'calmly',
        'dramatic': 'with dramatic flair',
        'humorous': 'with a touch of humor',
        'formal': 'formally',
        'friendly': 'warmly',
        'mysterious': 'mysteriously',
        'angry': 'with restrained anger',
        'sad': 'with melancholy'
    }
    tone_phrase = tone_map.get(tone_clean, f'in a {tone_clean} tone')
    action = ''
    if include_actions:
        action = f'*{role_clean} pauses and considers the question.* '
    context_phrase = ''
    if isinstance(context, str) and context.strip():
        context_phrase = f'Given that {context.strip()}, '
    answer = (
        f'{action}{role_clean} responds {tone_phrase}. '
        f'{context_phrase}You ask: {query_clean}. '
        f'As {role_clean}, I would say: I must act according to my nature, values, and current situation. '
        f'My answer is shaped by what I know and what I want. '
        f'If you need more detail, ask me to elaborate in character.'
    )
    if len(answer) > max_length:
        answer = answer[:max_length - 3].rstrip() + '...'
    return answer
