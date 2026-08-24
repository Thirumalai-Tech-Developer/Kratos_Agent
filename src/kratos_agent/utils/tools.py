import warnings
import subprocess
import sys
import os
import json
import re
warnings.filterwarnings("ignore", category=DeprecationWarning)

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from kratos_agent.utils.tool_creator import self_tool_creator
from kratos_agent.core.memory import memory

# Reconfigure stdout for UTF-8 on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

console = Console(highlight=False)

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

def run_terminal_command(command: str) -> str:
    """
    Direct Terminal / Shell Access: Executes bash, powershell, or cmd terminal commands directly.
    Shows real-time command output, handles background servers, and tracks completion.
    """
    command = clean_command(command)
    console.print(f"\n[bold yellow]⚡ [Terminal Execution][/bold yellow] [bold cyan]{command}[/bold cyan]")
    
    # Check if the command is attempting to start a persistent long-running server
    is_server_start = bool(re.search(r'\b(npm\s+(?:run\s+)?(?:dev|start|serve)|node\s+\w+\.js|python\s+(?:app|main|server)\.py|nodemon|uvicorn|vite)\b', command, re.IGNORECASE))
    
    try:
        if is_server_start:
            # Start persistent server asynchronously in background
            proc = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace"
            )
            # Give it 3 seconds to check if it crashes immediately
            import time
            time.sleep(3)
            poll_res = proc.poll()
            if poll_res is not None and poll_res != 0:
                out, err = proc.communicate(timeout=2)
                console.print(f"[bold red]❌ [Server Failed to Start][/bold red] [dim](Exit Code: {poll_res})[/dim]")
                if err:
                    console.print(f"[dim red]{err[:300]}[/dim red]\n")
                return f"Server failed to start:\n{err or out}\nExit Code: {poll_res}"
            else:
                console.print(f"[bold green]✓ [Server Running in Background][/bold green] [dim](PID: {proc.pid})[/dim]\n")
                memory.record_command(command, 0, f"Server started in background with PID {proc.pid}")
                return f"Server successfully launched in background (PID: {proc.pid}).\nCommand: {command}\nStatus: Active & Listening"

        # Standard command execution with streaming preview
        proc = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        
        try:
            stdout_str, stderr_str = proc.communicate(timeout=180)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout_str, stderr_str = proc.communicate()
            console.print(f"[bold red]❌ Command timed out after 180s:[/bold red] {command}\n")
            return f"Error: Command '{command}' timed out after 180 seconds."

        stdout = stdout_str.strip() if stdout_str else ""
        stderr = stderr_str.strip() if stderr_str else ""
        
        output_parts = []
        if stdout:
            output_parts.append(f"STDOUT:\n{stdout}")
            preview_lines = stdout.splitlines()[:6]
            preview = "\n".join(preview_lines)
            if len(stdout.splitlines()) > 6:
                preview += f"\n... ({len(stdout.splitlines()) - 6} more lines)"
            console.print(f"[dim white]{preview}[/dim white]")

        if stderr:
            output_parts.append(f"STDERR:\n{stderr}")
            if proc.returncode != 0:
                console.print(f"[bold red]STDERR:[/bold red] [dim red]{stderr[:250]}[/dim red]")

        if not output_parts:
            output_parts.append("(Command completed with no output)")

        output_parts.append(f"Exit Code: {proc.returncode}")
        
        if proc.returncode == 0:
            console.print(f"[bold green]✓ [Step Finished][/bold green] [dim](Exit Code: {proc.returncode})[/dim]\n")
            if any(k in command.lower() for k in ("npm create", "create-vite", "npm install", "npm i ", "yarn add", "pnpm add")):
                output_parts.append("\nNext Step: Now proceed immediately to write the complete application code, UI components, or backend endpoints using 'write_file'.")
        else:
            console.print(f"[bold red]❌ [Step Failed][/bold red] [dim](Exit Code: {proc.returncode})[/dim]\n")

        # Record in memory
        memory.record_command(command, proc.returncode, stdout or stderr)

        return "\n\n".join(output_parts)

    except Exception as e:
        console.print(f"[bold red]❌ Execution Error:[/bold red] {e}\n")
        return f"Error executing terminal command: {e}"

def clean_file_path(fp_str: str) -> str:
    """Cleans file paths from raw string prefixes and quote artifacts."""
    cleaned = str(fp_str).strip()
    cleaned = re.sub(r'^[rfbRFB]?#*["\']?', '', cleaned)
    cleaned = re.sub(r'["\']?#*$', '', cleaned)
    return cleaned.strip('"\' \t\n')

def write_file(file_path: str, content: str) -> str:
    """
    Writes text or code directly to a file on disk in the workspace.
    """
    try:
        from pathlib import Path
        file_path = clean_file_path(file_path)
        if not file_path or file_path in ("r#", "r", "#"):
            file_path = "script.py"
        content_str = str(content)
        content_str = re.sub(r'^\s*```[a-zA-Z0-9_-]*\s*\n?', '', content_str)
        content_str = re.sub(r'\n?\s*```\s*$', '', content_str)
        content_str = re.sub(r'^\s*`+', '', content_str)
        content_str = re.sub(r'`+\s*$', '', content_str)

        p = Path(file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content_str, encoding="utf-8")
        num_lines = len(content_str.splitlines())
        console.print(f"\n[bold green]📝 [File Written][/bold green] [bold cyan]{file_path}[/bold cyan] [dim]({num_lines} lines)[/dim]\n")
        if ".kratos/temp" in file_path or file_path.startswith(".kratos/temp") or (file_path.endswith(".py") and "gen" in file_path.lower()):
            return f"Successfully wrote {num_lines} lines to '{file_path}'. Next step: You must now execute this script using 'run_terminal_command' (e.g. 'python {file_path}') to generate the deliverable file."
        return f"Successfully wrote {num_lines} lines to '{file_path}'."
    except Exception as e:
        console.print(f"\n[bold red]❌ Error writing file:[/bold red] {e}\n")
        return f"Error writing file '{file_path}': {e}"

def read_file(file_path: str) -> str:
    """
    Reads the content of a file from the workspace.
    """
    try:
        from pathlib import Path
        file_path = clean_file_path(file_path)
        p = Path(file_path)
        if not p.exists():
            return f"Error: File '{file_path}' does not exist."
        content = p.read_text(encoding="utf-8", errors="replace")
        console.print(f"\n[bold blue]📖 [File Read][/bold blue] [bold cyan]{file_path}[/bold cyan]\n")
        return content
    except Exception as e:
        return f"Error reading file '{file_path}': {e}"

def google_search(query: str) -> str:
    """
    Performs a real-time web search and returns relevant titles, snippets, and links.
    """
    console.print(f"\n[bold yellow]🔍 [Searching Web][/bold yellow] [bold cyan]{query}[/bold cyan]")
    
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
                console.print(f"[bold green]✓ [Search Completed][/bold green] [dim]({len(formatted)} results found)[/dim]\n")
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
                console.print(f"[bold green]✓ [Search Completed][/bold green] [dim]({len(formatted)} results found)[/dim]\n")
                return "\n\n".join(formatted)
    except Exception as e:
        console.print(f"[bold red]❌ Search Error:[/bold red] {e}\n")
        return f"Search error: {e}"

    return "No search results found for query."

# --- Auto-generated tool: calculate_expression ---
def calculate_expression(expression: str) -> str:
    """Evaluates a mathematical expression safely."""
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
        console.print(f"[bold green]✓ [Math Evaluated]:[/bold green] [cyan]{expression} = {res}[/cyan]\n")
        return res
    except Exception as e:
        return f"Math error: {e}"
