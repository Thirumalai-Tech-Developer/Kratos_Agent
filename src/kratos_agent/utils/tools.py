import warnings
import subprocess
import sys
import os
import json
import re
import time
import difflib
from pathlib import Path
from typing import Optional, List, Dict, Any
warnings.filterwarnings("ignore", category=DeprecationWarning)

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from kratos_agent.utils.tool_creator import self_tool_creator
from kratos_agent.utils.step_tracker import step_tracker
from kratos_agent.core.memory import memory
from kratos_agent.core.approval_mode import approval_gate
from kratos_agent.core.hooks import hook_registry
from kratos_agent.core import git_tools as _git

# Reconfigure stdout for UTF-8 on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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
    cleaned = cleaned.rstrip('"} \t\n').lstrip('"{ \t\n')
    cleaned = re.sub(r'^\s*[`"\']+|[`"\']+\s*$', '', cleaned).strip()
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

def run_terminal_command(command: str) -> str:
    """
    Direct Terminal / Shell Access: Executes bash, powershell, or cmd terminal commands directly.
    Shows real-time dynamic single-line status, handles background servers, and tracks completion.
    """
    command = clean_command(command)
    # Codex-style approval gate + safety blocklist
    if not approval_gate.check_shell(command):
        return f"Shell command blocked by approval mode ({approval_gate.mode.value}): {command}"
    # Claude Code-style pre-tool hook
    hook_registry.fire("pre_tool_call", tool="run_terminal_command", input_str=command)
    step_tracker.start(f"Running: {command}")
    
    # Check if the command is attempting to start a persistent long-running server
    is_server_start = is_persistent_server_command(command)
    
    try:
        if is_server_start:
            proc = subprocess.Popen(
                command,
                shell=True,
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
            command,
            shell=True,
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
            step_tracker.fail(f"[bold red]Command timed out after 300s[/bold red]", command)
            return f"Error: Command '{command}' timed out after 300 seconds."
        except Exception as stream_err:
            try:
                proc.kill()
            except Exception:
                pass
            step_tracker.fail(f"[bold red]Execution error[/bold red]", str(stream_err))

        full_output = "".join(output_lines).strip()
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
        step_tracker.fail(f"[bold red]Execution error[/bold red]", str(e))
        return f"Error executing terminal command: {e}"

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
            except Exception:
                pass

        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content_str, encoding="utf-8")
        new_lines = content_str.splitlines()
        num_lines = len(new_lines)

        if not existed:
            stat_bar = f"[bold green]+{num_lines} lines[/bold green] [green]{'█' * min(10, max(1, num_lines // 15))}[/green]"
            step_tracker.complete(f"[bold white]Created[/bold white] [cyan]{file_path}[/cyan]", stat_bar, success=True)
            return f"Successfully created '{file_path}' (+{num_lines} lines)."
        else:
            diff = list(difflib.unified_diff(old_content.splitlines(), new_lines, lineterm=""))
            added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
            removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
            stat_bar = format_diff_stat(added, removed)
            step_tracker.complete(f"[bold white]Wrote[/bold white] [cyan]{file_path}[/cyan]", stat_bar, success=True)
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
            step_tracker.fail(f"[bold red]File not found[/bold red]", file_path)
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
            step_tracker.fail(f"[bold red]File not found[/bold red]", file_path)
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
            step_tracker.fail(f"[bold red]Directory not found[/bold red]", clean_dir)
            return f"Error: Directory '{directory_path}' does not exist."
        if not target.is_dir():
            step_tracker.fail(f"[bold red]Not a directory[/bold red]", clean_dir)
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
            step_tracker.fail(f"[bold red]Path not found[/bold red]", directory_path)
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
                    except Exception:
                        pass
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
        step_tracker.fail(f"[bold red]Grep search error[/bold red]", str(e))
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
    Performs a real-time web search and returns relevant titles, snippets, and links.
    """
    step_tracker.start(f"Searching web for '{query}'...")
    
    # 1. Try DuckDuckGo Search (DDGS)
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
            if results:
                formatted = []
                for idx, r in enumerate(results, 1):
                    title = r.get("title", "")
                    snippet = r.get("body", "")
                    href = r.get("href", "")
                    formatted.append(f"[{idx}] {title}\nSummary: {snippet}\nURL: {href}")
                step_tracker.complete(f"[bold white]Web search[/bold white] [cyan]'{query}'[/cyan]", f"{len(formatted)} results", success=True)
                return "\n\n".join(formatted)
    except Exception:
        pass

    # 2. Fallback to Wikipedia API Search
    try:
        import urllib.request
        from urllib.parse import quote_plus
        url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={quote_plus(query)}&format=json"
        req = urllib.request.Request(url, headers={"User-Agent": "KratosAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            search_items = data.get("query", {}).get("search", [])
            if search_items:
                formatted = []
                for idx, item in enumerate(search_items[:4], 1):
                    title = item.get("title", "")
                    snippet = re.sub(r"<[^>]+>", "", item.get("snippet", ""))
                    formatted.append(f"[{idx}] {title}\nSummary: {snippet}")
                step_tracker.complete(f"[bold white]Web search[/bold white] [cyan]'{query}'[/cyan]", f"{len(formatted)} results", success=True)
                return "\n\n".join(formatted)
    except Exception as e:
        step_tracker.fail(f"[bold red]Web search error[/bold red]", str(e))
        return f"Search error: {e}"

    step_tracker.complete(f"[bold white]Web search[/bold white] [cyan]'{query}'[/cyan]", "0 results", success=True)
    return "No search results found for query."

# --- Auto-generated tool: calculate_expression ---
def calculate_expression(expression: str) -> str:
    """Evaluates a mathematical expression safely."""
    step_tracker.start(f"Evaluating math: {expression}...")
    try:
        import ast, operator
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
        step_tracker.fail(f"[bold red]Math evaluation error[/bold red]", str(e))
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

