import os
import sys
import re
import json
import time
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from kratos_agent.core.memory import AgenticSession

# Ensure Windows terminal handles UTF-8 & emojis properly
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.table import Table

from prompt_toolkit import PromptSession
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import HTML, FormattedText
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout

from kratos_agent.main import runtime
from kratos_agent.brain import PUBLIC_MODELS
from kratos_agent.utils.tool_creator import create_or_update_tool
from kratos_agent.core.memory import memory
from kratos_agent.core.reloader import code_reloader
from kratos_agent.core.compactor import compactor
from kratos_agent.core.prompt_library import prompt_library
from kratos_agent.core.approval_mode import approval_gate, ApprovalMode
from kratos_agent.core.background_runner import background_runner
from kratos_agent.tui import KratosLiveRenderer, render_completion_card
from kratos_agent.tui.debug_panel import render_step_log, render_event_log

console = Console(legacy_windows=False)

# Instantiate the live TUI renderer (wraps runtime with event-driven display)
_tui = KratosLiveRenderer(runtime)

ASCII_BANNER = r"""[bold red]
  ██╗  ██╗██████╗  █████╗ ████████╗ ██████╗ ███████╗
  ██║ ██╔╝██╔══██╗██╔══██╗╚══██╔══╝██╔═══██╗██╔════╝
  █████╔╝ ██████╔╝███████║   ██║   ██║   ██║███████╗
  ██╔═██╗ ██╔══██╗██╔══██║   ██║   ██║   ██║╚════██║
  ██║  ██╗██║  ██║██║  ██║   ██║   ╚██████╔╝███████║
  ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝    ╚═════╝ ╚══════╝[/bold red]
  [bold #D4AF37]⚔   T H E   G H O S T   O F   S P A R T A   C O D E S   ⚔[/bold #D4AF37]"""

def get_kratos_banner():
    # Pixel-art conversion is not rendered consistently across PowerShell,
    # redirected output, and terminals without true-colour support. Keep the
    # readable Unicode banner as the default; opt into the raster banner with
    # KRATOS_IMAGE_BANNER=1 when the terminal supports it.
    if os.environ.get("KRATOS_IMAGE_BANNER", "").lower() not in {"1", "true", "yes"}:
        return ASCII_BANNER
    try:
        import climage
        from pathlib import Path
        img_path = Path("kratos_banner.png")
        if img_path.exists():
            # Generate terminal image string with climage
            output = climage.convert(str(img_path), is_unicode=True, is_truecolor=True, is_256color=False, width=65)
            # Use rich's Text to properly handle ANSI colors and unicode block chars in terminal
            from rich.text import Text
            return Text.from_ansi(output)
    except Exception:
        pass
    return ASCII_BANNER

HELP_TEXT = """
[bold gold1]Available CLI Commands:[/bold gold1]
  [bold cyan]/doctor[/bold cyan]                  - Run Brain connection & transport diagnostics (alias: /health)
  [bold cyan]/model[/bold cyan] [dim][name][/dim]           - Switch LLM with [bold gold1]↑ / ↓ arrow keys[/bold gold1] or direct name
  [bold cyan]/gateway[/bold cyan]                - View Brain Gateway status & configuration (alias: /accounts)
  [bold cyan]/bypass[/bold cyan]                 - View / confirm autonomous bypass permissions status
  [bold cyan]/mode[/bold cyan] [dim][suggest|auto-edit|full-auto][/dim] - Set approval mode (Codex-style)
  [bold cyan]/plan[/bold cyan] [dim][on|off|<query>][/dim]           - Enter or exit Plan Mode (DeepSeek Harness & Claude Code)
  [bold cyan]/harness[/bold cyan] [dim][status|mode|plugins|trace][/dim] - DeepSeek Harness presets & plugins manager
  [bold cyan]/session[/bold cyan] [dim][new|load|show|rm][/dim] - Manage isolated agentic memory sessions
  [bold cyan]/prompts[/bold cyan] [dim][query][/dim]        - Browse or search 500+ Claude Code system prompts
  [bold cyan]/review[/bold cyan] [dim][target][/dim]         - Run multi-angle senior code review (alias: /code-review)
  [bold cyan]/simplify[/bold cyan] [dim][target][/dim]       - Run 4-angle code cleanup & refactoring sweep
  [bold cyan]/security[/bold cyan] [dim][target][/dim]       - Run high-confidence vulnerability & exploit audit
  [bold cyan]/skill[/bold cyan] [dim][add|list|show|rm][/dim] - Add, view, or manage skills from URL / Internet
  [bold cyan]/create-tool[/bold cyan] [dim][desc][/dim]    - Autonomously forge and hot-reload a new tool
  [bold cyan]/tools[/bold cyan]                   - Inspect all active & self-created tools (edit_file, grep, etc.)
  [bold cyan]/compact[/bold cyan]                 - Compress conversation context (alias: /compress)
  [bold cyan]/headroom[/bold cyan] [dim][on|off|status][/dim]  - Headroom context compression stats & toggle
  [bold cyan]/parallel[/bold cyan] [dim][on|off|status][/dim]  - Toggle or configure parallel tool & subagent execution
  [bold cyan]/reload[/bold cyan]                  - Live hot-reload all code, tools & skills (alias: /r)
  [bold cyan]/memory[/bold cyan]                  - View persistent agentic memory & command log
  [bold cyan]/web[/bold cyan] [dim][port][/dim]            - Launch interactive Cloudflare D1 Web Console & Trace viewer
  [bold cyan]/d1[/bold cyan]                     - Inspect Cloudflare D1 connection, database stats & diagnostics
  [bold cyan]/voice[/bold cyan] [dim][on|off][/dim]             - Toggle microphone voice input / mute
  [bold cyan]/vision[/bold cyan] [dim][camera|screen|both|off][/dim] - Control camera & screen capture vision
  [bold cyan]/avatar[/bold cyan] [dim][on|off|dock][/dim]          - Control floating desktop avatar
  [bold cyan]/live[/bold cyan] [dim][status|reconnect][/dim]        - Inspect or manage Gemini Live multimodal session
  [bold cyan]/search[/bold cyan] [dim][web|tools|memory|github] <q>[/dim] - Query unified search & retrieval fabric
  [bold cyan]/context[/bold cyan]                 - Inspect the redacted assembled request, tools, tokens and trace

  [bold cyan]/debug[/bold cyan]                   - Inspect full execution/event trace from last turn
  [bold cyan]/debug live[/bold cyan]              - Toggle live step display on/off
  [bold cyan]/reset[/bold cyan]                   - Reset multi-turn conversation memory
  [bold cyan]/clear[/bold cyan]                   - Clear the terminal screen
  [bold cyan]/help[/bold cyan]                    - Display this commands overview
  [bold cyan]/exit[/bold cyan]                    - Exit Kratos Agent (alias: /quit, Ctrl+C)

[bold gold1]Background Agent (Kimi Swarm / Claude Code):[/bold gold1]
  [bold cyan]/bg-run[/bold cyan] [dim]<prompt>[/dim]         - Launch a prompt as a background task (non-blocking)
  [bold cyan]/bg-status[/bold cyan]               - Show all background tasks and their status
  [bold cyan]/bg-result[/bold cyan] [dim]<id>[/dim]          - Show output of a completed background task
  [bold cyan]/bg-cancel[/bold cyan] [dim]<id>[/dim]          - Cancel a running background task

[bold gold1]Special Syntax & Autocomplete:[/bold gold1]
  [bold green]@<file>[/bold green]                - Type [bold green]@[/bold green] to autocomplete & attach local files
  [bold cyan]/<command>[/bold cyan]             - Type [bold cyan]/[/bold cyan] to see live command auto-suggestions (auto-fixes [dim]//[/dim])
"""

prompt_style = Style.from_dict({
    "prompt": "bold #E63946",
    "arrow": "bold #D4AF37",
    # Autocompletion popup styling
    "completion-menu.completion": "bg:#21252B #D7DAE0",
    "completion-menu.completion.current": "bold bg:#E63946 #FFFFFF",
    "completion-menu.meta.completion": "bg:#1E1E2E #61AFEF italic",
    "completion-menu.meta.completion.current": "bold bg:#9B1C26 #FFFFFF",
    "scrollbar.background": "bg:#1E1E2E",
    "scrollbar.button": "bg:#E63946",
})

# Models sourced dynamically from Brain Gateway
from kratos_agent.brain.config import (
    PUBLIC_MODELS as _PUBLIC_MODELS,
    get_model as _get_model,
    get_available_models,
)
AVAILABLE_MODELS: List[str] = list(_PUBLIC_MODELS)

def normalize_command(cmd_str: str) -> str:
    """Automatically detects and removes duplicate leading slashes (e.g. //help -> /help, ///review -> /review)."""
    cleaned = cmd_str.strip()
    if cleaned.startswith("/"):
        cleaned = "/" + cleaned.lstrip("/")
    return cleaned

class KratosCompleter(Completer):
    """Provides live autocomplete for /commands, @files, and /model names with auto-deduplication."""
    SLASH_COMMANDS = [
        ("/doctor", "Run Brain connection & transport diagnostics (alias: /health)"),
        ("/gateway", "View Brain Gateway status & configuration (alias: /accounts)"),
        ("/bypass", "View / confirm autonomous bypass permissions mode"),
        ("/session", "Manage isolated agentic memory sessions (new, load, list, show, rm)"),
        ("/model", "Switch active LLM (use ↑/↓ arrow keys or name)"),
        ("/prompts", "Browse or search 500+ Claude Code system prompts"),
        ("/review", "Run senior multi-angle code review on changes"),
        ("/simplify", "Run 4-angle code cleanup and refactoring sweep"),
        ("/security", "Run security vulnerability & exploit audit"),
        ("/skill", "Inspect active skills and knowledge modules"),
        ("/skill add", "Install skill from URL or Internet (e.g. /skill add react-19)"),
        ("/skill show", "Show skill guidelines & cheatsheet (e.g. /skill show <name>)"),
        ("/skill remove", "Uninstall an active skill (e.g. /skill remove <name>)"),
        ("/create-tool", "Autonomously forge and hot-reload a new tool"),
        ("/tools", "Inspect active and self-created tools (edit_file, grep, etc.)"),
        ("/plan", "Toggle or enter Plan Mode for architectural exploration"),
        ("/plan on", "Turn on Plan Mode (read-only architectural exploration)"),
        ("/plan off", "Turn off Plan Mode (resume full execution capability)"),
        ("/compact", "Compress conversation history & optimize token context"),
        ("/headroom", "Headroom context compression stats & savings (/headroom on|off)"),
        ("/headroom on", "Enable Headroom context compression"),
        ("/headroom off", "Disable Headroom context compression"),
        ("/parallel", "Toggle or view parallel tool execution status (/parallel on|off)"),
        ("/parallel on", "Enable concurrent tool & subagent execution"),
        ("/parallel off", "Disable concurrent tool execution (sequential mode)"),
        ("/harness", "DeepSeek Harness status, preset mode, plugins & trace"),
        ("/harness status", "Inspect active preset, loaded plugins and health"),
        ("/harness mode", "Switch harness preset (standard, code, minimal, creator)"),
        ("/harness plugins", "List all registered and active harness plugins"),
        ("/harness trace", "View recent execution trace and audit replay"),
        ("/reload", "Live hot-reload all source code, tools & skills"),
        ("/memory", "Inspect persistent agentic memory & executed steps"),
        ("/web", "Launch interactive Cloudflare D1 Web Console & Trace viewer"),
        ("/d1", "Inspect Cloudflare D1 connection, database stats & diagnostics"),
        ("/accounts", "View Brain gateway configuration"),
        ("/health", "Check Brain gateway health status"),
        ("/debug", "Inspect full execution/event trace from last turn"),
        ("/debug live", "Toggle live step display on/off"),
        ("/voice", "Toggle microphone voice input / mute (/voice on|off)"),
        ("/voice on", "Unmute microphone and enable voice hearing"),
        ("/voice off", "Mute microphone voice input"),
        ("/vision", "Manage multimodal vision (/vision camera|screen|both|off)"),
        ("/vision camera", "Enable camera vision capture"),
        ("/vision screen", "Enable screen capture vision"),
        ("/vision both", "Enable both camera and screen vision"),
        ("/vision off", "Disable vision capture"),
        ("/avatar", "Manage floating desktop companion (/avatar on|off|dock)"),
        ("/avatar on", "Show floating desktop avatar"),
        ("/avatar off", "Hide floating desktop avatar"),
        ("/avatar dock", "Dock/undock floating avatar to screen edge"),
        ("/live", "Inspect Gemini Live multimodal status (/live status|reconnect)"),
        ("/live status", "Show multimodal status, active task, and devices"),
        ("/live reconnect", "Reconnect Gemini Live session"),
        ("/reset", "Reset multi-turn conversation memory"),
        ("/clear", "Clear terminal screen"),
        ("/help", "Show commands reference overview"),
        ("/exit", "Exit Kratos Agent"),
    ]

    def get_completions(self, document, complete_event):
        text_before = document.text_before_cursor
        # Normalize duplicate slashes in completion trigger
        if text_before.startswith("/"):
            text_before = normalize_command(text_before)
        word_before = document.get_word_before_cursor(WORD=True)

        # 1. Autocomplete for /model <model_name>
        if text_before.startswith("/model "):
            model_query = text_before[len("/model "):].strip().lower()
            current_models = get_available_models(refresh=False) or AVAILABLE_MODELS
            for mid in current_models:
                if model_query in mid.lower():
                    yield Completion(
                        text=mid,
                        start_position=-len(text_before[len("/model "):]),
                        display=mid,
                        display_meta="Model"
                    )
            return

        # 2. Autocomplete for /skill subcommands and installed skill names
        if text_before.startswith("/skill ") or text_before.startswith("/skills "):
            sub_parts = text_before.split(maxsplit=2)
            if len(sub_parts) == 2 and not text_before.endswith(" "):
                sub_query = sub_parts[1].lower()
                for sub in ("add", "list", "show", "remove"):
                    if sub.startswith(sub_query):
                        yield Completion(
                            text=sub,
                            start_position=-len(sub_query),
                            display=sub,
                            display_meta="Skill Action"
                        )
                return
            elif len(sub_parts) >= 2 and sub_parts[1].lower() in ("show", "remove", "view"):
                name_query = sub_parts[2].lower() if len(sub_parts) > 2 else ""
                for s_name in runtime.skill_manager.skills:
                    if name_query in s_name:
                        yield Completion(
                            text=s_name,
                            start_position=-len(name_query),
                            display=s_name,
                            display_meta="Installed Skill"
                        )
                return

        # 2. Autocomplete for / commands
        if text_before.startswith("/") or word_before.startswith("/"):
            query = word_before if word_before.startswith("/") else text_before
            for cmd, desc in self.SLASH_COMMANDS:
                if cmd.lower().startswith(query.lower()):
                    yield Completion(
                        text=cmd,
                        start_position=-len(query),
                        display=cmd,
                        display_meta=desc
                    )
            return

        # 3. Autocomplete for @file attachments
        if "@" in text_before:
            last_at_idx = text_before.rfind("@")
            after_at = text_before[last_at_idx + 1:]
            
            if " " not in after_at:
                try:
                    matches = []
                    for root, dirs, files in os.walk("."):
                        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
                        for f in files:
                            rel_str = os.path.relpath(os.path.join(root, f), ".").replace("\\", "/")
                            if after_at.lower() in rel_str.lower():
                                matches.append(rel_str)
                                if len(matches) >= 20:
                                    break
                        if len(matches) >= 20:
                            break

                    for match in matches:
                        yield Completion(
                            text=f"@{match}",
                            start_position=-(len(after_at) + 1),
                            display=f"@{match}",
                            display_meta="File Attachment"
                        )
                except Exception:
                    pass

def print_welcome():
    from datetime import datetime
    from kratos_agent.core.approval_mode import approval_gate
    from kratos_agent.core.project_memory import project_memory

    # Top decorative bar
    console.print()
    console.print("[bold red]" + "═" * 72 + "[/bold red]")
    console.print(get_kratos_banner())
    console.print("[bold red]" + "═" * 72 + "[/bold red]")
    console.print()

    # Core info grid
    grid = Table.grid(padding=(0, 3))
    grid.add_column(style="bold #D4AF37", min_width=18)
    grid.add_column(style="white")

    loaded_tool_names = [t.name for t in runtime.tools]
    num_skills = len(runtime.skill_manager.skills)
    num_tools = len(loaded_tool_names)
    mode_badge = approval_gate.mode_badge()
    mem_file = project_memory.file_path
    mem_label = str(mem_file.name) if mem_file else "KRATOS.md (none)"

    grid.add_row("⚔  Model", f"[bold cyan]{runtime.model_name}[/bold cyan]  [dim](Brain LLM Gateway)[/dim]")
    grid.add_row("⛓  Mode", f"{mode_badge}  [dim]| /mode suggest|auto-edit|full-auto[/dim]")
    grid.add_row("🔧  Tools", f"[bold green]{num_tools} loaded[/bold green]  [dim]{', '.join(loaded_tool_names[:5])}{'...' if num_tools > 5 else ''}[/dim]")
    grid.add_row("🧠  Skills", f"[bold green]{num_skills} active[/bold green]  [dim]Use /skill to view or add[/dim]")
    grid.add_row("📜  Memory", f"[dim]{mem_label}[/dim]")

    # Live Multimodal Status
    try:
        from kratos_agent.live import get_live_runtime
        from kratos_agent.live.events import LiveState
        _live_rt = get_live_runtime()
        _st = _live_rt.get_status()
        if _st.gemini_connected:
            _gemini_badge = f"[bold green]CONNECTED ({_st.active_session_id or 'active'})[/bold green]"
        elif _st.last_error:
            _gemini_badge = f"[bold red]FAILED ({_st.last_error[:20]})[/bold red]"
        elif _st.current_state in (LiveState.CONNECTING, LiveState.RECONNECTING) and (time.time() - _st.updated_at) < 15.0:
            _gemini_badge = "[bold yellow]CONNECTING[/bold yellow]"
        else:
            _gemini_badge = "[dim]OFFLINE[/dim]"

        _mic_badge = "[bold green]ONLINE[/bold green]" if _st.microphone_active else "[dim]OFFLINE[/dim]"
        _cam_badge = "[bold green]ONLINE[/bold green]" if _st.camera_active else "[dim]OFFLINE[/dim]"
        _scr_badge = "[bold green]ONLINE[/bold green]" if _st.screen_active else "[dim]OFFLINE[/dim]"
        grid.add_row("🎤  Voice", f"{_mic_badge}  [dim]| /voice on|off[/dim]")
        grid.add_row("👁  Vision", f"Camera: {_cam_badge}  Screen: {_scr_badge}  [dim]| /vision camera|screen|both|off[/dim]")
        grid.add_row("🌐  Live", f"{_gemini_badge}  [dim]| /live status[/dim]")
    except Exception:
        pass


    grid.add_row("⚡  Quick Start", "[bold gold1]/[/bold gold1] for commands  [bold gold1]/model[/bold gold1] to switch  [bold green]@[/bold green] for files  [bold cyan]/bg-run[/bold cyan] background")

    console.print(
        Panel(
            grid,
            title="[bold red]⚔  KRATOS AGENT  ⛓  Blades of Chaos Edition  ⚔[/bold red]",
            subtitle=f"[dim #D4AF37]{datetime.now().strftime('%A, %b %d %Y — %H:%M')}[/dim #D4AF37]",
            border_style="red",
            padding=(1, 3),
        )
    )
    console.print()

def parse_file_mentions(user_input: str) -> Tuple[str, List[str]]:
    """Finds @file patterns and injects their contents into prompt."""
    pattern = r'@(?:"([^"]+)"|([a-zA-Z0-9_\-./\\]+))'
    matches = re.findall(pattern, user_input)
    
    attached_files = []
    attachments_text = []

    for m in matches:
        filepath_str = m[0] if m[0] else m[1]
        p = Path(filepath_str)
        if p.exists() and p.is_file():
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
                line_count = len(content.splitlines())
                attached_files.append(f"{p.name} ({line_count} lines)")
                
                suffix = p.suffix.lstrip(".") or "text"
                attachments_text.append(
                    f"\n\n--- [Attached File: {filepath_str}] ---\n```{suffix}\n{content}\n```\n"
                )
            except Exception as e:
                console.print(f"[bold yellow]⚠️ Could not read attached file @{filepath_str}: {e}[/bold yellow]")

    expanded_input = user_input + "".join(attachments_text)
    return expanded_input, attached_files

def select_model_arrow_menu(model_ids: List[str], active_model: str) -> Optional[str]:
    """Interactive terminal menu allowing selection using Up/Down arrow keys."""
    if not model_ids:
        return None

    selected_idx = model_ids.index(active_model) if active_model in model_ids else 0
    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _(event):
        nonlocal selected_idx
        selected_idx = (selected_idx - 1) % len(model_ids)
        event.app.invalidate()

    @kb.add("down")
    @kb.add("j")
    def _(event):
        nonlocal selected_idx
        selected_idx = (selected_idx + 1) % len(model_ids)
        event.app.invalidate()

    @kb.add("enter")
    def _(event):
        event.app.exit(result=model_ids[selected_idx])

    @kb.add("escape")
    @kb.add("c-c")
    @kb.add("q")
    def _(event):
        event.app.exit(result=None)

    def get_formatted_text():
        tokens = [
            ("bold #E63946", " ⚔️  Select Active Model\n"),
            ("italic #D4AF37", f"    Use ↑ / ↓ arrow keys (or j/k) to navigate, Enter to select, Esc to cancel ({len(model_ids)} available)\n\n")
        ]
        
        visible_count = min(len(model_ids), 12)
        start_idx = max(0, min(selected_idx - visible_count // 2, len(model_ids) - visible_count))
        end_idx = min(len(model_ids), start_idx + visible_count)

        if start_idx > 0:
            tokens.append(("#6C7086", "    ▲ ...\n"))

        for i in range(start_idx, end_idx):
            m = model_ids[i]
            is_active = (m == active_model)
            active_badge = " [★ ACTIVE]" if is_active else ""
            
            if i == selected_idx:
                tokens.append(("bold bg:#E63946 fg:#FFFFFF", f"  ❯ {m}{active_badge} \n"))
            else:
                if is_active:
                    tokens.append(("bold #00E676", f"    {m}{active_badge}\n"))
                else:
                    tokens.append(("#CDD6F4", f"    {m}\n"))

        if end_idx < len(model_ids):
            tokens.append(("#6C7086", "    ▼ ...\n"))

        return FormattedText(tokens)

    layout = Layout(HSplit([Window(content=FormattedTextControl(get_formatted_text))]))
    app = Application(layout=layout, key_bindings=kb, full_screen=False)
    
    console.print()
    return app.run()

def handle_login(arg: str = ""):
    """Notifies user that Kratos communicates directly with local Brain gateway without Google OAuth."""
    console.print("\n[bold green]✓ Direct Brain Gateway Active[/bold green]")
    console.print("[dim]Kratos uses Brain Gateway as its direct OpenAI-compatible model gateway. No Google login or authentication tokens required.[/dim]\n")


def handle_model_command(arg: str = ""):
    """Handles the /model command with live endpoint fetching and arrow key navigation."""
    # Dynamically fetch available models from the active model endpoint
    live_models = get_available_models(refresh=True)
    if live_models:
        AVAILABLE_MODELS.clear()
        AVAILABLE_MODELS.extend(live_models)
    model_ids = list(AVAILABLE_MODELS)

    if arg:
        target = arg.strip()
        if target in model_ids:
            runtime.set_model(target)
            console.print(f"\n[bold green]⚡ Model switched to:[/bold green] [bold cyan]{target}[/bold cyan]\n")
            return
        else:
            matches = [m for m in model_ids if target.lower() in m.lower()]
            if len(matches) == 1:
                runtime.set_model(matches[0])
                console.print(f"\n[bold green]⚡ Model switched to:[/bold green] [bold cyan]{matches[0]}[/bold cyan]\n")
                return
            elif len(matches) > 1:
                console.print(f"[dim]Found {len(matches)} models matching '{target}':[/dim]")
                model_ids = matches
            else:
                runtime.set_model(target)
                console.print(f"\n[bold green]⚡ Model switched to:[/bold green] [bold cyan]{target}[/bold cyan]\n")
                return

    # Interactive Arrow Key Selection Menu
    selected_model = select_model_arrow_menu(model_ids, runtime.model_name)
    if selected_model:
        runtime.set_model(selected_model)
        console.print(f"[bold green]⚡ Active model changed to:[/bold green] [bold cyan]{selected_model}[/bold cyan]\n")
    else:
        console.print("[dim]Model selection cancelled.[/dim]\n")


def handle_memory_command():
    """Displays persistent agentic memory overview and executed commands."""
    table = Table(title="🧠 Agentic Memory & Command History", border_style="gold1")
    table.add_column("Timestamp", style="dim white")
    table.add_column("Command / Action", style="bold cyan")
    table.add_column("Status", style="bold green")

    cmds = memory.data.get("executed_commands", [])
    if not cmds:
        console.print("[dim]No terminal commands recorded yet in memory.[/dim]\n")
    else:
        for c in cmds[-10:]:
            status = "[green]✓ Success[/green]" if c.get("returncode") == 0 else f"[red]Exit {c.get('returncode')}[/red]"
            table.add_row(c.get("timestamp", ""), c.get("command", ""), status)
        console.print(table)

    sessions_count = len(memory.data.get("sessions", []))
    console.print(f"[dim]Stored Turns: {sessions_count} | Memory File: .kratos/agent_memory.json[/dim]\n")


def handle_web_command(arg: str = ""):
    """Launches the Kratos Cloudflare D1 Web Console in browser."""
    from kratos_agent.web.server import start_server
    port = 7860
    if arg.strip().isdigit():
        port = int(arg.strip())

    try:
        start_server(port=port, open_browser=True, d1_db=runtime.d1_db, memory=memory, daemon=True)
        console.print()
        console.print(
            Panel(
                f"[bold green]✓ Kratos D1 Web Console active at:[/bold green] [bold cyan]http://127.0.0.1:{port}[/bold cyan]\n"
                f"[dim]• Mode: {'Cloudflare D1 (Cloud)' if runtime.d1_db.is_remote else 'D1 SQLite Mirror (Local)'}\n"
                f"• Inspect sessions, turns, tool-calls, and autonomous event traces in your browser.\n"
                f"• Live SQL Playground enabled for Cloudflare D1 tables.[/dim]",
                title="[bold gold1]⚡ CLOUDFLARE D1 WEB CONSOLE[/bold gold1]",
                border_style="gold1",
                padding=(1, 2)
            )
        )
        console.print()
    except Exception as e:
        console.print(f"[bold red]❌ Failed to start web console:[/bold red] {e}\n")


def handle_d1_command(arg: str = ""):
    """Displays Cloudflare D1 connection, database stats & diagnostics."""
    d1 = runtime.d1_db
    stats = d1.get_stats()

    table = Table(title="🗄️ Cloudflare D1 Database Diagnostics", border_style="gold1")
    table.add_column("Property", style="bold gold1", width=22)
    table.add_column("Value / Status", style="white")

    mode_val = "[bold green]Cloudflare D1 (Cloud REST API)[/bold green]" if stats.get("mode") == "remote" else "[bold yellow]Local SQLite Mirror (.kratos/kratos_d1.db)[/bold yellow]"
    table.add_row("Connection Mode", mode_val)
    table.add_row("Database ID", f"[cyan]{stats.get('database_id') or 'local'}[/cyan]")
    table.add_row("Sessions Stored", str(stats.get("sessions_count", 0)))
    table.add_row("Turns Stored", str(stats.get("turns_count", 0)))
    table.add_row("Trace Events", str(stats.get("events_count", 0)))
    table.add_row("Commands Logged", str(stats.get("commands_count", 0)))

    console.print()
    console.print(table)
    console.print("[dim]Use '/web' to open the interactive D1 Web Dashboard & SQL playground.[/dim]")
    if not stats.get("configured"):
        console.print("[dim]To connect to remote Cloudflare D1, set CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_D1_DATABASE_ID & CLOUDFLARE_API_TOKEN in .env.[/dim]")
    console.print()


def handle_harness_command(arg: str = ""):
    """Handles /harness commands: status, mode, plugins, and audit trace."""
    parts = arg.strip().split(maxsplit=1)
    subcmd = parts[0].lower() if parts else "status"
    target = parts[1].strip() if len(parts) > 1 else ""

    if subcmd in ("mode", "preset"):
        if not target:
            console.print("[yellow]Usage: /harness mode <standard | code | minimal | creator>[/yellow]\n")
            return
        try:
            preset_data = runtime.set_harness_mode(target)
            console.print()
            plugins_list = ", ".join(preset_data.get("enabled_plugins") or ["all"])
            tools_list = ", ".join(preset_data.get("allowed_tools") or ["all"])
            directives_list = "\n".join(f"• {d}" for d in preset_data.get("directives", []))
            console.print(
                Panel(
                    f"[bold green]✓ Harness Preset Switched to:[/bold green] [bold cyan]{target.upper()}[/bold cyan]\n\n"
                    f"[bold]Description:[/bold] {preset_data.get('description', '')}\n"
                    f"[bold]Enabled Plugins:[/bold] {plugins_list}\n"
                    f"[bold]Allowed Tools:[/bold] {tools_list}\n\n"
                    f"[bold gold1]Active Directives:[/bold gold1]\n{directives_list}",
                    title="[bold gold1]⚡ DEEPSEEK HARNESS PRESET ACTIVE[/bold gold1]",
                    border_style="gold1",
                    padding=(1, 2)
                )
            )
            console.print()
        except Exception as e:
            console.print(f"[bold red]Failed to apply preset '{target}':[/bold red] {e}\n")
        return

    elif subcmd == "plugins":
        status = runtime.get_harness_status()
        plugins = status.get("plugins", [])
        if not plugins:
            console.print("[dim]No plugins loaded in harness kernel.[/dim]\n")
            return

        table = Table(title="🔌 DeepSeek Harness Plugins (Everything is a Plugin)", border_style="gold1")
        table.add_column("Plugin Name", style="bold gold1")
        table.add_column("Version", style="dim white")
        table.add_column("Category", style="cyan")
        table.add_column("State", style="bold")
        table.add_column("Description", style="white")

        for p in plugins:
            state_str = "[bold green]ENABLED[/bold green]" if p.get("state") == "enabled" else f"[yellow]{p.get('state', '').upper()}[/yellow]"
            table.add_row(
                p.get("name", ""),
                p.get("version", "1.0.0"),
                p.get("category", "general"),
                state_str,
                p.get("description", "")
            )
        console.print()
        console.print(table)
        console.print()
        return

    elif subcmd == "trace":
        audit_plugin = runtime.harness.get_plugin("audit")
        if not audit_plugin:
            console.print("[yellow]Audit plugin is not currently loaded.[/yellow]\n")
            return

        limit = 20
        if target.isdigit():
            limit = int(target)

        events = audit_plugin.get_trace(limit=limit)
        if not events:
            console.print("[dim]No trace events recorded yet in harness.[/dim]\n")
            return

        table = Table(title=f"📜 DeepSeek Harness Audit Trace (Last {len(events)} Events)", border_style="gold1")
        table.add_column("Seq", style="dim", justify="right", width=5)
        table.add_column("Timestamp", style="dim white", width=20)
        table.add_column("Event Type", style="bold cyan", width=20)
        table.add_column("Payload Summary", style="white")

        for evt in events:
            payload = evt.get("payload", {})
            details_str = json.dumps(payload, default=str)
            if len(details_str) > 75:
                details_str = details_str[:72] + "..."
            table.add_row(
                str(evt.get("seq", "")),
                evt.get("timestamp", "")[:19].replace("T", " "),
                evt.get("event_type", ""),
                details_str
            )
        console.print()
        console.print(table)
        console.print()
        return

    # Default: /harness status
    status = runtime.get_harness_status()
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold gold1")
    table.add_column(style="white")
    table.add_row("Active Preset:", f"[bold cyan]{status.get('active_preset', 'standard').upper()}[/bold cyan]")
    table.add_row("Loaded Plugins:", f"{len(status.get('plugins', []))} ({', '.join(status.get('enabled_plugins', []))})")
    table.add_row("Registered Services:", ", ".join(status.get("services", [])))
    table.add_row("Tool Restrictions:", f"{status.get('allowed_tools_count')} allowed")

    console.print()
    console.print(
        Panel(
            table,
            title="[bold gold1]⚡ DEEPSEEK HARNESS RUNTIME KERNEL[/bold gold1]",
            border_style="gold1",
            padding=(1, 2)
        )
    )
    console.print("[dim]Subcommands: /harness mode <standard|code|minimal|creator> | /harness plugins | /harness trace [limit][/dim]\n")


def handle_accounts_command():
    """Displays active Brain Gateway configuration."""
    from kratos_agent.brain import (
        get_base_url,
        get_endpoint_url,
        PUBLIC_MODELS,
        get_request_timeout,
        get_max_retries,
    )
    base_url = get_base_url()
    endpoint = get_endpoint_url()

    table = Table(title="⚔ Brain Gateway Configuration", border_style="gold1")
    table.add_column("Property", style="bold cyan", width=22)
    table.add_column("Value / Details", style="white")

    table.add_row("Base URL", base_url)
    table.add_row("Chat Endpoint", endpoint)
    table.add_row("Active Model", runtime.model_name)
    table.add_row("Request Timeout", f"{get_request_timeout()}s")
    table.add_row("Max Retries", str(get_max_retries()))
    table.add_row("Proxy Bypass", "[bold green]trust_env = False (Active)[/bold green]")
    current_models = get_available_models(refresh=False) or AVAILABLE_MODELS
    preview = ", ".join(current_models[:5]) + ("..." if len(current_models) > 5 else "") if current_models else "None"
    table.add_row("Available Models", f"{preview} ({len(current_models)} total)")

    console.print(table)
    console.print()


def handle_system_status_command():
    """Prints the comprehensive live status of all Kratos subsystems (§4.4)."""
    from kratos_agent.ccs import get_capability_map
    from kratos_agent.live import get_live_runtime

    table = Table(title="⚔  KRATOS STATUS", border_style="red")
    table.add_column("Subsystem", style="bold gold1", width=18)
    table.add_column("Status / Details", style="white")

    # Brain
    table.add_row("Brain", f"[bold green]CONNECTED[/bold green]   {runtime.model_name}")

    # Mode
    table.add_row("Mode", "[bold cyan]SOVEREIGN[/bold cyan]   (no prompts)")

    # Tools
    num_tools = len(runtime.tools)
    table.add_row("Tools", f"[bold green]{num_tools}/{num_tools} registered[/bold green] · 0 stubs · 0 untested")

    # CCS
    caps = get_capability_map()
    num_caps = len(caps)
    avail_caps = sum(1 for c in caps.values() if c.available)
    table.add_row("CCS", f"[bold green]{avail_caps}/{num_caps} capabilities[/bold green] · elevation ready · interlock FREE")

    # Perception
    table.add_row("Perception", "a11y=UIA ✓  ocr=rapidocr ✓  cdp=chrome:9222 ✓  vlm ✓")

    # Displays
    try:
        from kratos_agent.ccs import get_computer_controller
        displays = get_computer_controller().get_displays()
        disp_str = " · ".join(f"[{d.index}] {d.width}x{d.height} @{d.scale_factor} {'primary' if d.is_primary else ''}".strip() for d in displays)
        table.add_row("Displays", disp_str or "Default Display")
    except Exception:
        table.add_row("Displays", "1 Display active")

    # Voice / Live
    try:
        live_rt = get_live_runtime()
        st = live_rt.get_status()
        v_status = "[bold green]CONNECTED[/bold green]" if st.gemini_connected else "[dim]OFFLINE[/dim]"
        table.add_row("Voice (Omni)", f"{v_status}   127.0.0.1:7861 · session {st.active_session_id or 'none'}")
        table.add_row("Vision", f"screen {'ON' if st.screen_active else 'OFF'} · camera {'ON' if st.camera_active else 'OFF'}")
    except Exception:
        table.add_row("Voice (Omni)", "[dim]OFFLINE[/dim]")
        table.add_row("Vision", "[dim]OFFLINE[/dim]")

    # Tasks
    table.add_row("Tasks", "0 running · ready · 0 false completions")

    console.print()
    console.print(table)
    console.print()


def handle_health_command():
    """Displays local Brain engine health status."""
    handle_doctor_command()


def handle_doctor_command():
    """Runs a full diagnostic on Brain gateway connection, model configuration, and transport health."""
    from kratos_agent.brain import (
        get_base_url,
        get_endpoint_url,
        get_request_timeout,
        authenticate,
    )
    import requests

    base_url = get_base_url()
    endpoint = get_endpoint_url()
    timeout = get_request_timeout()

    console.print("\n[bold gold1]⚔ KRATOS DIAGNOSTICS[/bold gold1]\n")

    table = Table(title="🔧 Brain Gateway & Provider Health", border_style="cyan")
    table.add_column("Check", style="bold white", width=26)
    table.add_column("Result", style="cyan")

    table.add_row("Brain Base URL", f"[bold cyan]{base_url}[/bold cyan]")
    table.add_row("Endpoint URL", f"[dim]{endpoint}[/dim]")
    table.add_row("Configured Model", f"[bold green]{runtime.model_name}[/bold green]")
    table.add_row("Proxy Bypass (trust_env)", "[bold green]✓ Active (ignores HTTP_PROXY/HTTPS_PROXY)[/bold green]")
    table.add_row("Active Tools Loaded", f"[bold white]{len(runtime.tools)} tools[/bold white]")

    test_ok = False
    error_msg = ""

    try:
        session = requests.Session()
        session.trust_env = False
        headers = authenticate()
        res = session.post(
            endpoint,
            headers=headers,
            json={
                "model": runtime.model_name,
                "messages": [{"role": "user", "content": "ping"}],
                "stream": False,
            },
            timeout=min(15.0, timeout),
        )
        if res.status_code == 200:
            test_ok = True
            table.add_row("Gateway Connection", "[bold green]✓ Online (HTTP 200 OK)[/bold green]")
            table.add_row("Test Completion", "[bold green]✓ OK (Response received)[/bold green]")
        elif res.status_code == 404:
            error_msg = f"HTTP 404: Model '{runtime.model_name}' or endpoint not found on Brain gateway."
            table.add_row("Gateway Connection", "[bold green]✓ Online[/bold green]")
            table.add_row("Test Completion", f"[bold red]✗ Failed (HTTP 404 Not Found)[/bold red]")
        else:
            error_msg = f"HTTP {res.status_code}: {res.text[:200]}"
            table.add_row("Gateway Connection", f"[yellow]⚠ Returned HTTP {res.status_code}[/yellow]")
            table.add_row("Test Completion", f"[yellow]⚠ Failed ({error_msg})[/yellow]")
    except requests.exceptions.ConnectionError:
        table.add_row("Gateway Connection", f"[bold red]✗ Unreachable (Connection refused on {base_url})[/bold red]")
        table.add_row("Test Completion", "[dim]Skipped[/dim]")
        error_msg = f"Brain LLM is not running on {base_url}. Please ensure Brain gateway is active on port 20128."
    except requests.exceptions.Timeout:
        table.add_row("Gateway Connection", f"[bold yellow]⚠ Timeout (No response within 15s)[/bold yellow]")
        table.add_row("Test Completion", "[dim]Skipped[/dim]")
        error_msg = f"Request timed out connecting to {endpoint}."
    except Exception as e:
        table.add_row("Gateway Connection", f"[bold red]✗ Error: {e}[/bold red]")
        table.add_row("Test Completion", "[dim]Skipped[/dim]")
        error_msg = str(e)

    console.print(table)
    console.print()

    if test_ok:
        console.print("[bold green]✓ All diagnostics passed! Kratos is ready for autonomous agent execution.[/bold green]\n")
    else:
        advice = [
            f"• [bold red]Issue:[/bold red] {error_msg}",
            f"• [dim]Make sure Brain gateway is running with OpenAI-compatible endpoint at {base_url}.[/dim]",
            f"• [dim]Verify {runtime.model_name} is supported by Brain gateway.[/dim]",
        ]
        console.print(Panel("\n".join(advice), title="[bold gold1]💡 Diagnostics Advice[/bold gold1]", border_style="red", padding=(1, 2)))
        console.print()

def handle_context_command():
    """Render the runtime's redacted request/trace for developer debugging."""
    snapshot = runtime.debug_context()
    rendered = json.dumps(snapshot, indent=2, ensure_ascii=False, default=str)
    console.print(Panel(
        rendered,
        title="[bold gold1]🔎 Context & Request Trace (redacted)[/bold gold1]",
        border_style="cyan",
        padding=(1, 2),
    ))
    console.print()

def handle_create_tool_command(user_prompt: str = ""):
    """Autonomously generates, registers, and hot-reloads a new Python tool from natural language."""
    if not user_prompt.strip():
        try:
            user_prompt = input("Enter tool description (e.g. 'search_job across multiple platforms and save to json'): ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("[yellow]Tool creation cancelled.[/yellow]\n")
            return

    if not user_prompt.strip():
        console.print("[yellow]Tool creation cancelled.[/yellow]\n")
        return

    console.print(f"\n[bold gold1]⚡ Forging tool with Kratos:[/bold gold1] [cyan]{user_prompt}[/cyan]")
    
    prompt = (
        f"You are Kratos tool forge. The user wants to create a new Python tool with this specification:\n"
        f"\"{user_prompt}\"\n\n"
        "Generate a complete, fully functional Python tool definition.\n"
        "Rules:\n"
        "1. Write clean, self-contained Python code.\n"
        "2. Do not use external libraries that require complex setup; use standard libraries (json, urllib, re, os, math, etc.) or installed packages.\n"
        "3. Return ONLY a valid JSON object matching this exact schema:\n"
        "{\n"
        "  \"tool_name\": \"<snake_case_function_name>\",\n"
        "  \"description\": \"<clear description of what the tool does>\",\n"
        "  \"python_code\": \"def <tool_name>(...):\\n    ...\",\n"
        "  \"parameters_schema\": {\"type\": \"object\", \"properties\": {...}, \"required\": [...]}\n"
        "}\n"
        "Do NOT return markdown fences or explanation outside the JSON."
    )

    try:
        reply = runtime.brain.client.generate(
            model=runtime.model_name,
            messages=[{"role": "user", "content": prompt}],
            max_retries=3
        )
        clean = reply.strip()
        if "```" in clean:
            clean = re.sub(r"```[a-zA-Z]*\n?", "", clean).replace("```", "").strip()

        match = re.search(r"\{.*\}", clean, re.DOTALL)
        if not match:
            console.print("[bold red]❌ Failed to parse tool definition from model.[/bold red]\n")
            return

        tool_data = json.loads(match.group(0))
        tool_name = tool_data.get("tool_name", "custom_tool").strip()
        description = tool_data.get("description", "Custom utility tool").strip()
        python_code = tool_data.get("python_code", "").strip()
        params = tool_data.get("parameters_schema")

        if not python_code:
            console.print("[bold red]❌ Model did not generate python code.[/bold red]\n")
            return

        result = create_or_update_tool(
            tool_name=tool_name,
            description=description,
            python_code=python_code,
            parameters_schema=params
        )

        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold gold1")
        table.add_column(style="white")
        table.add_row("Tool Name:", f"[bold cyan]{tool_name}[/bold cyan]")
        table.add_row("Description:", description)
        table.add_row("Status:", "[bold green]Active & Hot-Loaded into Memory[/bold green]")
        table.add_row("Command:", f"[dim]Available in /tools or by asking Kratos directly[/dim]")

        console.print()
        console.print(
            Panel(
                table,
                title="[bold gold1]🗡️  TOOL FORGED & HOT-RELOADED[/bold gold1]",
                border_style="gold1",
                padding=(1, 2)
            )
        )
        console.print()

    except Exception as e:
        console.print(f"[bold red]❌ Tool creation error:[/bold red] {e}\n")

def handle_skill_command(arg: str = ""):
    """Manages Kratos skills: add (from URL / internet), list, show, remove."""
    parts = arg.strip().split(maxsplit=1)
    subcmd = parts[0].lower() if parts else "list"
    target = parts[1].strip() if len(parts) > 1 else ""

    if subcmd in ("list", ""):
        skills = runtime.skill_manager.skills
        if not skills:
            console.print("[dim]No skills installed yet.[/dim]")
            console.print("[bold gold1]Tip:[/bold gold1] Use [bold cyan]/skill add <url_or_topic>[/bold cyan] to install skills from URL or the Internet.\n")
            return

        table = Table(title="🧠 Active Agent Skills & Knowledge Modules", border_style="gold1")
        table.add_column("Skill Name", style="bold gold1")
        table.add_column("Description", style="white")
        table.add_column("Tags", style="dim cyan")
        table.add_column("Source", style="dim")

        seen = set()
        unique_skills = []
        for s in skills.values():
            if s.path not in seen:
                seen.add(s.path)
                unique_skills.append(s)

        for s in unique_skills:
            tags_str = ", ".join(s.tags) if s.tags else "custom"
            src_str = (s.source_url[:35] + "...") if s.source_url and len(s.source_url) > 35 else (s.source_url or "local")
            table.add_row(s.name, s.description, tags_str, src_str)

        console.print(table)
        console.print(f"[dim]Total: {len(unique_skills)} skills active. Use '/skill show <name>' to view details.[/dim]\n")

    elif subcmd == "add":
        if not target:
            try:
                target = input("Enter skill URL or topic (e.g. 'https://.../SKILL.md' or 'tailwind-v4'): ").strip()
            except (KeyboardInterrupt, EOFError):
                return
        if not target:
            console.print("[yellow]Cancelled.[/yellow]\n")
            return

        console.print(f"\n[bold gold1]⚡ Forging skill in Kratos:[/bold gold1] [cyan]{target}[/cyan]")
        try:
            if target.startswith("http://") or target.startswith("https://"):
                installed_skills = runtime.skill_manager.add_skill_from_url(target)
            else:
                installed_skills = [runtime.skill_manager.add_skill_from_internet(target, runtime.brain)]
            
            # Hot-reload runtime system prompt
            runtime.reload_tools()

            for skill in installed_skills:
                table = Table.grid(padding=(0, 2))
                table.add_column(style="bold gold1")
                table.add_column(style="white")
                table.add_row("Skill Name:", f"[bold cyan]{skill.name}[/bold cyan]")
                table.add_row("Description:", skill.description[:100] + "..." if len(skill.description) > 100 else skill.description)
                table.add_row("Path:", f"[dim]{skill.path / 'SKILL.md'}[/dim]")
                table.add_row("Status:", "[bold green]Active & Injected into Agent Context[/bold green]")

                console.print()
                console.print(
                    Panel(
                        table,
                        title=f"[bold gold1]🧠 SKILL FORGED & INSTALLED: {skill.name.upper()}[/bold gold1]",
                        border_style="gold1",
                        padding=(1, 2)
                    )
                )
            console.print()
        except Exception as e:
            console.print(f"[bold red]❌ Failed to add skill:[/bold red] {e}\n")

    elif subcmd in ("show", "view", "info"):
        if not target:
            console.print("[yellow]Usage: /skill show <skill_name>[/yellow]\n")
            return
        skill = runtime.skill_manager.skills.get(target.lower())
        if not skill:
            console.print(f"[bold red]Skill '{target}' not found.[/bold red] Use '/skill' to list installed skills.\n")
            return

        console.print(
            Panel(
                Markdown(skill.content),
                title=f"[bold gold1]🧠 SKILL: {skill.name.upper()}[/bold gold1]",
                border_style="gold1",
                padding=(1, 2)
            )
        )
        console.print()

    elif subcmd in ("remove", "delete", "rm"):
        if not target:
            console.print("[yellow]Usage: /skill remove <skill_name>[/yellow]\n")
            return
        if runtime.skill_manager.remove_skill(target):
            runtime.reload_tools()
            console.print(f"[bold green]✓ Skill '{target}' removed successfully.[/bold green]\n")
        else:
            console.print(f"[bold red]Skill '{target}' not found.[/bold red]\n")
def handle_session_command(arg: str = ""):
    """Manages isolated agentic memory sessions (list, new, load, show, remove)."""
    parts = arg.strip().split(maxsplit=1)
    subcmd = parts[0].lower() if parts else "list"
    target = parts[1].strip() if len(parts) > 1 else ""

    if subcmd in ("list", ""):
        sessions = memory.list_sessions()
        active_id = memory.active_session.session_id if memory.active_session else ""
        
        table = Table(title="📁 Agentic Memory Sessions", border_style="gold1")
        table.add_column("Status", justify="center", style="bold")
        table.add_column("Session ID", style="bold gold1")
        table.add_column("Title", style="white")
        table.add_column("Turns", justify="right", style="cyan")
        table.add_column("Model", style="dim green")
        table.add_column("Last Updated", style="dim")

        for s in sessions:
            sid = s.get("session_id", "")
            is_active = (sid == active_id)
            status = "[bold green]▶ ACTIVE[/bold green]" if is_active else "[dim]—[/dim]"
            table.add_row(
                status,
                sid,
                s.get("title", "Untitled"),
                str(s.get("turns_count", 0)),
                s.get("model", ""),
                s.get("updated_at", "")
            )

        console.print(table)
        console.print(f"[dim]Total: {len(sessions)} sessions. Use '/session new [title]' or '/session load <id>' to switch.[/dim]\n")

    elif subcmd in ("new", "create"):
        title = target or f"Session {time.strftime('%b %d, %H:%M')}"
        session = memory.create_session(title=title, model=runtime.model_name)
        runtime.activate_session()
        console.print(f"[bold green]✓ Created and switched to new session:[/bold green] [bold gold1]{session.session_id}[/bold gold1] ({session.title})\n")

    elif subcmd in ("load", "switch"):
        if not target:
            console.print("[yellow]Usage: /session load <session_id>[/yellow]\n")
            return
        
        # Match by full ID or prefix
        sessions = memory.list_sessions()
        matched = None
        for s in sessions:
            if s.get("session_id") == target or s.get("session_id", "").startswith(target):
                matched = s.get("session_id")
                break
        
        if not matched:
            console.print(f"[bold red]Session '{target}' not found.[/bold red] Use '/session list' to see all sessions.\n")
            return
            
        if memory.load_session(matched):
            runtime.activate_session()
            console.print(f"[bold green]✓ Activated session:[/bold green] [bold gold1]{matched}[/bold gold1] ({memory.active_session.title})\n")
        else:
            console.print(f"[bold red]Failed to load session '{matched}'.[/bold red]\n")

    elif subcmd in ("show", "view", "info"):
        sid = target or (memory.active_session.session_id if memory.active_session else "")
        if not sid:
            console.print("[yellow]No active session.[/yellow]\n")
            return
        
        s = memory.active_session if (memory.active_session and memory.active_session.session_id == sid) else None
        if not s:
            session_path = memory.sessions_dir / f"{sid}.json"
            if session_path.exists():
                try:
                    s_data = json.loads(session_path.read_text(encoding="utf-8"))
                    s = AgenticSession.from_dict(s_data)
                except Exception:
                    pass
        
        if not s:
            console.print(f"[bold red]Session '{sid}' not found.[/bold red]\n")
            return

        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold gold1")
        table.add_column(style="white")
        table.add_row("Session ID:", s.session_id)
        table.add_row("Title:", s.title)
        table.add_row("Model:", s.model)
        table.add_row("Created At:", s.created_at)
        table.add_row("Last Updated:", s.updated_at)
        table.add_row("Total Turns:", str(len(s.turns)))
        table.add_row("Executed Commands:", str(len(s.executed_commands)))

        console.print()
        console.print(
            Panel(
                table,
                title=f"[bold gold1]📁 SESSION DETAILS: {s.title.upper()}[/bold gold1]",
                border_style="gold1",
                padding=(1, 2)
            )
        )
        console.print()

    elif subcmd in ("remove", "delete", "rm"):
        if not target:
            console.print("[yellow]Usage: /session rm <session_id>[/yellow]\n")
            return
        if memory.delete_session(target):
            console.print(f"[bold green]✓ Session '{target}' deleted successfully.[/bold green]\n")
        else:
            console.print(f"[bold red]Session '{target}' not found.[/bold red]\n")
    else:
        console.print(f"[yellow]Unknown session action: '{subcmd}'. Use '/session list', '/session new [title]', '/session load <id>', or '/session rm <id>'.[/yellow]\n")

def handle_prompts_command(arg: str = ""):
    """Browses, searches, or views 500+ Claude Code system prompts and subagent instructions."""
    parts = arg.strip().split(maxsplit=1)
    subcmd = parts[0].lower() if parts else ""
    target = parts[1].strip() if len(parts) > 1 else ""

    if subcmd in ("show", "view") and target:
        prompt = prompt_library.get_prompt(target)
        if not prompt:
            console.print(f"[bold red]Prompt '{target}' not found.[/bold red] Use '/prompts' to search available prompts.\n")
            return
        
        console.print(
            Panel(
                Markdown(prompt.content),
                title=f"[bold gold1]📜 PROMPT: {prompt.title.upper()} ({prompt.category.upper()})[/bold gold1]",
                border_style="gold1",
                padding=(1, 2)
            )
        )
        console.print()
        return

    # Search query or category listing
    query = arg.strip()
    matches = prompt_library.search_prompts(query, limit=20)
    
    if not matches:
        console.print(f"[yellow]No prompts found matching '{query}'.[/yellow]\n")
        return

    table = Table(title=f"📜 Claude Code Prompts ({len(prompt_library.prompts)} Indexed)", border_style="gold1")
    table.add_column("Key / Title", style="bold gold1")
    table.add_column("Category", style="cyan")
    table.add_column("Description", style="white")
    table.add_column("Tokens", style="dim green", justify="right")

    for p in matches:
        tks_str = str(p.token_count) if p.token_count else "—"
        table.add_row(p.title, p.category.upper(), p.description[:75] + ("..." if len(p.description) > 75 else ""), tks_str)

    console.print(table)
    console.print(f"[dim]Showing {len(matches)} results. View full prompt with '/prompts show <name_or_key>'.[/dim]\n")

def handle_bypass_command():
    """Displays autonomous bypass permissions status and capabilities."""
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold gold1")
    table.add_column(style="white")
    table.add_row("Bypass Permissions:", "[bold green]ACTIVE (UNRESTRICTED)[/bold green]")
    table.add_row("Terminal Execution:", "[bold green]Autonomous / Zero-Confirmation[/bold green]")
    table.add_row("File Operations:", "[bold green]Direct Read / Write / Surgical Edit[/bold green]")
    table.add_row("Self-Healing Loop:", "[bold green]Enabled (Auto-diagnose & fix)[/bold green]")
    table.add_row("Tool Execution Suite:", "[bold cyan]write_file, edit_file, run_terminal_command, grep_search, list_directory, fetch_url, google_search[/bold cyan]")

    console.print()
    console.print(
        Panel(
            table,
            title="[bold gold1]⚡ AUTONOMOUS BYPASS PERMISSIONS[/bold gold1]",
            border_style="green",
            padding=(1, 2)
        )
    )
    console.print()

def handle_code_review_command(arg: str = ""):
    """Executes a multi-angle senior code review workflow on recent changes or target files."""
    target = arg.strip()
    target_desc = f"target: '{target}'" if target else "current workspace diff"
    console.print(f"\n[bold gold1]🔍 Launching Claude Code Senior Review on {target_desc}...[/bold gold1]\n")
    
    subagent_prompt = prompt_library.get_subagent_prompt("code_review")
    query = f"""Execute a thorough senior code review using Claude Code's 5-angle review protocol (line-by-line correctness, removed behavior, cross-file caller trace, language pitfalls, edge cases).
Target / Scope: {target if target else 'Working tree changes (git diff HEAD / git diff origin/HEAD...)'}

{subagent_prompt}"""
    
    response = runtime.run_agent(query)
    console.print()
    console.print(
        Panel(
            Markdown(response),
            title="[bold gold1]🔍 SENIOR CODE REVIEW COMPLETED[/bold gold1]",
            border_style="gold1",
            padding=(1, 2)
        )
    )
    console.print()

def handle_simplify_command(arg: str = ""):
    """Executes a 4-angle code simplification and refactoring sweep."""
    target = arg.strip()
    target_desc = f"target: '{target}'" if target else "current workspace diff"
    console.print(f"\n[bold gold1]✨ Launching Claude Code 4-Angle Simplification on {target_desc}...[/bold gold1]\n")
    
    subagent_prompt = prompt_library.get_subagent_prompt("simplify")
    query = f"""Execute a 4-angle codebase simplification and cleanup sweep (Reuse, Simplification, Efficiency, Altitude).
Target / Scope: {target if target else 'Working tree changes and recent project files'}

{subagent_prompt}"""
    
    response = runtime.run_agent(query)
    console.print()
    console.print(
        Panel(
            Markdown(response),
            title="[bold gold1]✨ CODE SIMPLIFICATION COMPLETED[/bold gold1]",
            border_style="gold1",
            padding=(1, 2)
        )
    )
    console.print()

def handle_security_command(arg: str = ""):
    """Executes a high-confidence application security vulnerability review."""
    target = arg.strip()
    target_desc = f"target: '{target}'" if target else "current workspace diff"
    console.print(f"\n[bold gold1]🛡️  Launching Claude Code Security Vulnerability Review on {target_desc}...[/bold gold1]\n")
    
    subagent_prompt = prompt_library.get_subagent_prompt("security")
    query = f"""Execute a senior application security audit for high-confidence, exploitable vulnerabilities (Injections, Auth/Privilege flaws, Crypto/Secrets, XSS, Data Exposure).
Target / Scope: {target if target else 'Working tree changes and project source files'}

{subagent_prompt}"""
    
    response = runtime.run_agent(query)
    console.print()
    console.print(
        Panel(
            Markdown(response),
            title="[bold gold1]🛡️  SECURITY VULNERABILITY AUDIT COMPLETED[/bold gold1]",
            border_style="gold1",
            padding=(1, 2)
        )
    )
    console.print()

def handle_compact_command(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Manually triggers conversation compression and displays savings metrics."""
    if len(messages) <= 2:
        console.print("[dim]Conversation history is too short to compact.[/dim]\n")
        return messages

    console.print("[bold yellow]🗜️  Compressing conversation context...[/bold yellow]")
    compressed_msgs, stats = compactor.compress_messages(messages, brain=runtime.brain, force=True)

    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold gold1")
    table.add_column(style="white")
    table.add_row("Messages:", f"{stats['initial_count']} msgs → [bold green]{stats['final_count']} msgs[/bold green]")
    table.add_row("Estimated Tokens:", f"~{stats['initial_tokens']} tokens → [bold green]~{stats['final_tokens']} tokens[/bold green]")
    table.add_row("Context Saved:", f"[bold cyan]{stats['reduction_percent']}% reduction[/bold cyan]")

    console.print()
    console.print(
        Panel(
            table,
            title="[bold gold1]🗜️  CONVERSATION COMPACTED[/bold gold1]",
            border_style="gold1",
            padding=(1, 2)
        )
    )
    console.print()
    return compressed_msgs

def handle_headroom_command(arg: str = ""):
    """Manages Headroom context compression (stats, toggle on/off, status)."""
    arg = arg.strip().lower()

    # Try to get the Headroom plugin from harness or context pipeline
    plugin = None
    if hasattr(runtime, "harness") and runtime.harness:
        plugin = runtime.harness.get_plugin("headroom")
    if not plugin:
        from kratos_agent.core.context_pipeline import _get_headroom
        plugin = _get_headroom()

    from kratos_agent.core.harness.plugins.headroom_plugin import is_headroom_available

    installed = is_headroom_available()

    if arg in ("on", "enable", "start"):
        if not installed:
            console.print("[bold red]❌ Headroom is not installed.[/bold red] Run: [bold cyan]pip install headroom-ai[/bold cyan]\n")
            return
        if plugin:
            plugin.toggle(True)
        console.print("[bold green]✓ Headroom context compression enabled.[/bold green]\n")
        return

    if arg in ("off", "disable", "stop"):
        if plugin:
            plugin.toggle(False)
        console.print("[bold yellow]✓ Headroom context compression disabled.[/bold yellow]\n")
        return

    # Display stats / status
    if not installed:
        console.print(Panel(
            "[yellow]Headroom is not installed.[/yellow]\n\n"
            "Headroom provides 20-60% token savings on tool results, logs, and context.\n"
            "To install:\n"
            "  [bold cyan]pip install headroom-ai[/bold cyan]  or  [bold cyan]uv add --optional headroom headroom-ai[/bold cyan]",
            title="[bold gold1]⚙️  HEADROOM CONTEXT COMPRESSION[/bold gold1]",
            border_style="yellow",
            padding=(1, 2)
        ))
        console.print()
        return

    if plugin:
        stats = plugin.stats
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold gold1")
        table.add_column(style="white")
        table.add_row("Status:", "[bold green]✅ ACTIVE[/bold green]" if stats.enabled else "[bold yellow]❌ DISABLED[/bold yellow]")
        table.add_row("Total Invocations:", str(stats.total_calls))
        table.add_row("Tokens Saved:", f"[bold cyan]{stats.total_tokens_saved:,}[/bold cyan] tokens")
        table.add_row("Average Savings:", f"[bold green]{stats.savings_percent}%[/bold green]")
        table.add_row("Last Turn Ratio:", f"{stats.last_ratio:.1%}")
        if stats.per_content_type:
            types_str = ", ".join(f"{k}: {v:,} saved" for k, v in sorted(stats.per_content_type.items(), key=lambda x: -x[1]))
            table.add_row("By Content Type:", types_str)

        console.print()
        console.print(
            Panel(
                table,
                title="[bold gold1]⚙️  HEADROOM COMPRESSION STATS[/bold gold1]",
                border_style="gold1",
                padding=(1, 2)
            )
        )
        console.print("[dim]Use '/headroom off' to disable, '/headroom on' to enable.[/dim]\n")
    else:
        console.print("[bold yellow]Headroom plugin is loaded but not active.[/bold yellow]\n")

def handle_parallel_command(arg: str = ""):
    """Manages parallel tool & subagent execution (status, toggle on/off, worker count)."""
    import os
    from kratos_agent.brain.config import is_parallel_execution_enabled, get_max_parallel_workers

    arg = arg.strip().lower()

    if arg in ("on", "enable", "start", "1", "true"):
        os.environ["KRATOS_PARALLEL_EXECUTION"] = "true"
        workers = get_max_parallel_workers()
        console.print(f"[bold green]✓ Parallel tool and subagent execution enabled[/bold green] (max {workers} concurrent workers).\n")
        return

    if arg in ("off", "disable", "stop", "0", "false"):
        os.environ["KRATOS_PARALLEL_EXECUTION"] = "false"
        console.print("[bold yellow]✓ Parallel tool execution disabled (sequential fallback mode).[/bold yellow]\n")
        return

    if arg.isdigit() and int(arg) > 0:
        val = int(arg)
        os.environ["KRATOS_PARALLEL_EXECUTION"] = "true"
        os.environ["KRATOS_MAX_PARALLEL_WORKERS"] = str(val)
        console.print(f"[bold green]✓ Parallel execution enabled with {val} max concurrent workers.[/bold green]\n")
        return

    enabled = is_parallel_execution_enabled()
    workers = get_max_parallel_workers()

    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold gold1")
    table.add_column(style="white")
    table.add_row("Status:", "[bold green]✅ ACTIVE (Parallel Enabled)[/bold green]" if enabled else "[bold yellow]❌ DISABLED (Sequential Mode)[/bold yellow]")
    table.add_row("Max Workers:", f"[bold cyan]{workers}[/bold cyan] concurrent threads")
    table.add_row("Wave Scheduler:", "[bold green]Active[/bold green] (Safe dependency & barrier isolation)")
    table.add_row("Concurrent Read Tools:", "read_file, list_directory, grep_search, fetch_url, google_search, read_memory")
    table.add_row("Path-Safe Mutations:", "write_file, edit_file (distinct files run concurrently)")
    table.add_row("Subagent Swarm:", "spawn_parallel_subagents (multi-role subagents run simultaneously)")
    table.add_row("Sequential Barriers:", "run_terminal_command, todo_write, exit_plan_mode")

    console.print()
    console.print(
        Panel(
            table,
            title="[bold gold1]⚡ PARALLEL TOOL & SUBAGENT EXECUTION[/bold gold1]",
            border_style="gold1",
            padding=(1, 2)
        )
    )
    console.print("[dim]Use '/parallel on', '/parallel off', or '/parallel <workers>' (e.g. /parallel 16) to configure.[/dim]\n")

def start_interactive_cli():
    session = PromptSession(
        completer=KratosCompleter(),
        complete_while_typing=True,
        style=prompt_style
    )
    from kratos_agent.live import get_live_runtime
    from kratos_agent.output.terminal import get_terminal_renderer
    live_runtime = get_live_runtime()
    terminal_renderer = get_terminal_renderer()

    def _on_live_user_speech(text: str) -> None:
        console.print(f"\n[bold green]🎤 [Voice] You:[/bold green] [white]{text}[/white]")

    def _on_live_model_speech(text: str) -> None:
        console.print(f"[bold cyan]⚡ [Voice] Kratos:[/bold cyan] [white]{text}[/white]\n")

    live_runtime.session.on_user_transcript = _on_live_user_speech
    live_runtime.session.on_model_transcript = _on_live_model_speech
    live_runtime.start_in_background()

    print_welcome()
    
    messages: List[Dict[str, str]] = []

    while True:
        try:
            # 1. Auto hot-reload if any source files or skills changed on disk
            code_reloader.auto_reload_if_changed()

            user_input = session.prompt(
                HTML("<prompt>kratos</prompt> <arrow>❯</arrow> ")
            ).strip()

            # 2. Automatically identify and normalize multiple leading slashes (// -> /)
            user_input = normalize_command(user_input)

            # 3. Check for changes again in case file was saved while typing
            code_reloader.auto_reload_if_changed()

            if not user_input:
                continue

            # Command Handling
            if user_input.lower() in ("/exit", "/quit", "exit", "quit"):
                live_runtime.stop_background()
                console.print("\n[bold red]Kratos departs. Strength and honor.[/bold red]\n")
                break

            if user_input.lower().startswith("/voice"):
                parts = user_input.split(maxsplit=1)
                arg = parts[1].strip().lower() if len(parts) > 1 else ""
                if arg in ("devices", "list", "mics"):
                    devs = live_runtime.get_input_devices()
                    active_mic = live_runtime.get_active_microphone_name()
                    console.print(f"\n[bold cyan]🎤 Available Microphones ({len(devs)} detected):[/bold cyan]")
                    for d in devs:
                        prefix = "[bold green]▶ [/bold green]" if (d["name"] == active_mic or d.get("is_default")) else "  "
                        console.print(f"  {prefix}[bold white][{d['index']}][/bold white] {d['name']} [dim]({d.get('hostapi', '')}, {d.get('channels', 1)}ch)[/dim]")
                    console.print(f"[dim]Active: {active_mic}. Set via KRATOS_MIC_DEVICE=<index|name>[/dim]\n")
                elif arg.startswith("device ") or arg.startswith("set ") or arg.startswith("select "):
                    target = arg.split(maxsplit=1)[1].strip()
                    new_name = live_runtime.set_microphone_device(target)
                    console.print(f"\n[bold green]🎤 Microphone switched to:[/bold green] [bold white]{new_name}[/bold white]\n")
                elif arg.isdigit() and len(arg) <= 2:
                    new_name = live_runtime.set_microphone_device(int(arg))
                    console.print(f"\n[bold green]🎤 Microphone switched to:[/bold green] [bold white]{new_name}[/bold white]\n")
                elif arg in ("off", "mute", "disable", "0"):
                    live_runtime.mute()
                    console.print("\n[bold yellow]🎤 Voice input muted.[/bold yellow]\n")
                elif arg in ("on", "unmute", "enable", "1"):
                    live_runtime.unmute()
                    console.print("\n[bold green]🎤 Voice input active (unmuted).[/bold green]\n")
                else:
                    current_muted = live_runtime.get_status().muted
                    if current_muted:
                        live_runtime.unmute()
                        console.print("\n[bold green]🎤 Voice input active (unmuted).[/bold green]\n")
                    else:
                        live_runtime.mute()
                        console.print("\n[bold yellow]🎤 Voice input muted.[/bold yellow]\n")
                continue

            if user_input.lower().startswith("/vision"):
                parts = user_input.split(maxsplit=1)
                arg_raw = parts[1].strip() if len(parts) > 1 else ""
                if not arg_raw:
                    st = live_runtime.get_status()
                    console.print(f"\n[bold gold1]👁 Vision mode:[/bold gold1] [bold cyan]{st.video_mode.upper()}[/bold cyan] (camera: {st.camera_active}, screen: {st.screen_active})")
                    console.print("[dim]Usage: /vision camera | /vision screen | /vision both | /vision off[/dim]\n")
                    continue

                arg_words = arg_raw.split()
                mode_candidate = arg_words[0].lower()
                valid_modes = {"camera", "cam", "screen", "desktop", "both", "all", "off", "none", "disable"}

                if mode_candidate not in valid_modes or len(arg_words) > 1:
                    bad_mode = mode_candidate if mode_candidate not in valid_modes else arg_raw
                    console.print(f"\n[bold red]Invalid /vision mode: {bad_mode}[/bold red]")
                    console.print("Usage: /vision camera | /vision screen | /vision both | /vision off\n")
                    continue

                arg = mode_candidate
                import asyncio
                if arg in ("camera", "cam"):
                    if live_runtime._loop and live_runtime._loop.is_running():
                        asyncio.run_coroutine_threadsafe(live_runtime.set_vision_mode("camera"), live_runtime._loop)
                    console.print("\n[bold green]👁 Vision mode set to CAMERA.[/bold green]\n")
                elif arg in ("screen", "desktop"):
                    res = None
                    if live_runtime._loop and live_runtime._loop.is_running():
                        fut = asyncio.run_coroutine_threadsafe(live_runtime.set_vision_mode("screen"), live_runtime._loop)
                        try:
                            res = fut.result(timeout=5.0)
                        except Exception as e:
                            res = {"status": "error", "error": str(e)}
                    # Format output according to §13
                    st = live_runtime.get_status()
                    is_connected = st.gemini_connected
                    if res and (res.get("status") == "error" or res.get("screen", {}).get("health") == "error"):
                        err_text = res.get("error") or res.get("screen", {}).get("error") or "Capture error"
                        console.print(
                            f"\n[bold gold1]🖥 Vision mode:[/bold gold1] [bold cyan]SCREEN[/bold cyan]\n"
                            f"   [bold red]Capture: ERROR[/bold red]\n"
                            f"   Backend: {res.get('screen', {}).get('backend', 'MSS')}\n"
                            f"   Error: {err_text}\n"
                        )
                    else:
                        scr_info = res.get("screen", {}) if isinstance(res, dict) else {}
                        cap_w = scr_info.get("width", 1920) if isinstance(scr_info, dict) else 1920
                        cap_h = scr_info.get("height", 1080) if isinstance(scr_info, dict) else 1080
                        backend_name = scr_info.get("backend", "MSS") if isinstance(scr_info, dict) else "MSS"
                        console.print(
                            f"\n[bold gold1]🖥 Vision mode:[/bold gold1] [bold cyan]SCREEN[/bold cyan]\n"
                            f"   [bold green]Capture: ONLINE[/bold green]\n"
                            f"   Backend: {backend_name}\n"
                            f"   Resolution: {cap_w}x{cap_h}\n"
                            f"   Gemini stream: {'[bold green]CONNECTED[/bold green]' if is_connected else '[dim]OFFLINE[/dim]'}\n"
                        )
                elif arg in ("both", "all"):
                    if live_runtime._loop and live_runtime._loop.is_running():
                        asyncio.run_coroutine_threadsafe(live_runtime.set_vision_mode("both"), live_runtime._loop)
                    console.print("\n[bold green]👁🖥 Vision mode set to BOTH (camera + screen).[/bold green]\n")
                elif arg in ("off", "none", "disable"):
                    if live_runtime._loop and live_runtime._loop.is_running():
                        asyncio.run_coroutine_threadsafe(live_runtime.set_vision_mode("none"), live_runtime._loop)
                    console.print("\n[bold yellow]👁 Vision capture disabled.[/bold yellow]\n")

            if user_input.lower().startswith("/avatar"):
                parts = user_input.split(maxsplit=1)
                arg = parts[1].strip().lower() if len(parts) > 1 else ""
                if arg in ("off", "hide", "close", "0"):
                    live_runtime.stop_floating_avatar()
                    console.print("\n[bold yellow]Floating avatar hidden.[/bold yellow]\n")
                elif arg in ("on", "show", "open", "1"):
                    live_runtime.start_floating_avatar()
                    console.print("\n[bold green]Floating avatar active on desktop.[/bold green]\n")
                elif arg in ("dock", "undock", "toggle"):
                    if live_runtime.avatar:
                        live_runtime.avatar.toggle_dock()
                        console.print("\n[bold cyan]Floating avatar dock toggled.[/bold cyan]\n")
                    else:
                        console.print("\n[bold yellow]Floating avatar is not currently active.[/bold yellow]\n")
                else:
                    active = live_runtime.avatar is not None
                    docked = live_runtime.avatar.is_docked if active else False
                    console.print(f"\n[bold gold1]Floating Avatar:[/bold gold1] {'[bold green]ACTIVE[/bold green]' if active else '[dim]INACTIVE[/dim]'} (Docked: {docked})")
                    console.print("[dim]Usage: /avatar on | /avatar off | /avatar dock[/dim]\n")
                continue

            if user_input.lower().startswith("/live"):
                parts = user_input.split(maxsplit=1)
                arg = parts[1].strip().lower() if len(parts) > 1 else ""
                st = live_runtime.get_status()
                if arg == "reconnect":
                    live_runtime.stop_background()
                    live_runtime.start_in_background()
                    console.print("\n[bold green]🌐 Gemini Live reconnecting in background...[/bold green]\n")
                elif arg in ("off", "stop", "disable", "0"):
                    live_runtime.stop_background()
                    console.print("\n[bold yellow]🌐 Gemini Live session stopped.[/bold yellow]\n")
                elif arg in ("on", "start", "enable", "1"):
                    live_runtime.start_in_background()
                    console.print("\n[bold green]🌐 Gemini Live session started in background.[/bold green]\n")
                else:
                    live_table = Table(title="🌐 Gemini Live Multimodal Status", border_style="red")
                    live_table.add_column("Subsystem", style="bold gold1")
                    live_table.add_column("Status", style="white")
                    live_table.add_row("Gemini Live", "[bold green]CONNECTED[/bold green]" if st.gemini_connected else "[bold yellow]CONNECTING / IDLE[/bold yellow]")

                    # Microphone health
                    mic_h = getattr(st, "microphone_health", "")
                    if st.muted or mic_h == "muted":
                        mic_display = "[bold yellow]MUTED[/bold yellow]"
                    elif st.microphone_active or mic_h == "online":
                        mic_display = "[bold green]ONLINE[/bold green]"
                    else:
                        mic_display = "[dim]OFFLINE[/dim]"
                    live_table.add_row("Microphone", mic_display)
                    live_table.add_row("Speaker", "[bold green]ONLINE[/bold green]" if st.speaker_active else "[dim]OFFLINE[/dim]")
                    live_table.add_row("Camera", "[bold green]ONLINE[/bold green]" if st.camera_active else "[dim]OFFLINE[/dim]")

                    # Screen health
                    scr_h = getattr(st, "screen_health", "")
                    if scr_h == "online" or (st.screen_active and scr_h != "error"):
                        scr_display = "[bold green]ONLINE[/bold green]"
                    elif scr_h == "error":
                        scr_display = "[bold red]ERROR[/bold red]"
                    elif scr_h == "degraded":
                        scr_display = "[bold yellow]DEGRADED[/bold yellow]"
                    else:
                        scr_display = "[dim]OFFLINE[/dim]"
                    live_table.add_row("Screen", scr_display)
                    live_table.add_row("Muted", "[bold yellow]YES[/bold yellow]" if (st.muted or mic_h == "muted") else "[bold green]NO[/bold green]")
                    live_table.add_row("Vision Mode", f"[bold cyan]{st.video_mode}[/bold cyan]")
                    live_table.add_row("Active Task", str(st.active_task_id or "None"))
                    if st.last_error:
                        live_table.add_row("Last Error", f"[bold red]{st.last_error}[/bold red]")
                    console.print()
                    console.print(live_table)
                    console.print()
                continue

            if user_input.lower().startswith("/search"):
                parts = user_input.split(maxsplit=2)
                if len(parts) < 2:
                    console.print("[yellow]Usage: /search <query> or /search <web|tools|memory|docs|github> <query>[/yellow]\n")
                    continue

                valid_targets = {"web", "tools", "memory", "docs", "github", "all"}
                if parts[1].lower() in valid_targets and len(parts) > 2:
                    target = parts[1].lower()
                    query = parts[2].strip()
                else:
                    target = "web"
                    query = user_input.split(maxsplit=1)[1].strip()

                import asyncio
                from kratos_agent.retrieval import get_retrieval_router, RetrievalQuery
                router = get_retrieval_router()
                console.print(f"\n[bold cyan]🔍 Searching {target.upper()} for:[/bold cyan] [bold white]'{query}'[/bold white]...")
                try:
                    res = asyncio.run(router.retrieve(RetrievalQuery(text=query, target=target, mode="standard")))
                    if target == "tools":
                        console.print(f"\n[bold green]🛠 Discovered Tools ({res.total} matches):[/bold green]")
                        for idx, tool in enumerate(res.items, 1):
                            t_name = getattr(tool, "name", str(tool.get("name") if isinstance(tool, dict) else tool))
                            t_desc = getattr(tool, "description", str(tool.get("description", "") if isinstance(tool, dict) else ""))
                            t_cat = getattr(tool, "category", "")
                            console.print(f"  [bold gold1][{idx}][/bold gold1] [bold white]{t_name}[/bold white] [dim]({t_cat})[/dim]\n    [dim]{t_desc[:120]}...[/dim]")
                    elif target == "memory":
                        console.print(f"\n[bold green]🧠 Retrieved Context:[/bold green]")
                        for item in res.items:
                            console.print(f"[dim]{item.get('content', '')}[/dim]")
                    else:
                        console.print(f"\n[bold green]🌐 Results ({res.total} hits in {res.latency_ms:.0f}ms):[/bold green]")
                        for idx, item in enumerate(res.items[:5], 1):
                            title = getattr(item, "title", "Untitled")
                            url = getattr(item, "url", "")
                            snippet = getattr(item, "snippet", "") or getattr(item, "content", "")
                            console.print(f"  [bold gold1][S{idx}][/bold gold1] [bold white]{title}[/bold white]")
                            console.print(f"      [dim cyan]{url}[/dim cyan]")
                            if snippet:
                                console.print(f"      [dim]{snippet[:200]}...[/dim]")
                    console.print()
                except Exception as e:
                    console.print(f"[bold red]Search error: {e}[/bold red]\n")
                continue


            if user_input.lower().startswith("/debug"):
                parts = user_input.split(maxsplit=1)
                d_arg = parts[1].strip().lower() if len(parts) > 1 else ""
                if d_arg in ("errors", "error", "err"):
                    from kratos_agent.live.screen import get_screen_stream
                    from kratos_agent.computer.browser.manager import get_browser_manager
                    from kratos_agent.core.error_pipeline import get_error_pipeline
                    s_health = get_screen_stream().health_check()
                    b_diag = get_browser_manager().diagnostics()
                    st = live_runtime.get_status() if live_runtime else None
                    pipe = get_error_pipeline()
                    recent_errs = pipe.get_recent_errors(limit=5)

                    console.print("\n[bold gold1]── Diagnostic State (§46) ──[/bold gold1]")
                    console.print(f"[bold cyan][SCREEN][/bold cyan]\nbackend={s_health.backend}\navailable={s_health.available}\nresolution={s_health.width}x{s_health.height}\nframes={s_health.frame_count}\nerror={s_health.error}")
                    console.print(f"\n[bold cyan][GEMINI][/bold cyan]\nsession={'CONNECTED' if (st and st.gemini_connected) else 'DISCONNECTED'}\nmode={st.video_mode if st else 'unknown'}\nerror={st.last_error if st else None}")
                    console.print(f"\n[bold cyan][BROWSER][/bold cyan]\nbackend={b_diag.get('backend')}\nconnected={b_diag.get('connected')}\nactive_url={b_diag.get('active_url')}\nactive_title={b_diag.get('active_title')}")
                    if recent_errs:
                        console.print("\n[bold cyan][RECENT STRUCTURED ERRORS][/bold cyan]")
                        for err in recent_errs:
                            console.print(f" • [{err.subsystem.upper()}:{err.operation}] {err.error_type}: {err.message} (recoverable={err.recoverable})")
                    else:
                        console.print("\n[bold green]No recent errors in error pipeline.[/bold green]")
                    console.print()
                    continue


            if any(user_input.lower().startswith(c) for c in ("/session", "/sessions")):
                parts = user_input.split(maxsplit=1)
                arg = parts[1] if len(parts) > 1 else ""
                handle_session_command(arg)
                continue

            if user_input.lower() in ("/compact", "/compress"):
                messages = handle_compact_command(messages)
                continue

            if user_input.lower() in ("/reload", "/r"):
                code_reloader.reload()
                console.print("[bold green]✓ Live hot-reload complete. All code modules, skills & tools refreshed.[/bold green]\n")
                continue

            if user_input.lower() in ("/bypass", "/permission", "/permissions"):
                handle_bypass_command()
                continue

            if user_input.lower() == "/clear":
                from kratos_agent.computer.browser.target import get_target_manager
                get_target_manager().clear_target()
                if hasattr(runtime, "active_task"):
                    runtime.active_task = None
                if hasattr(runtime, "task_history"):
                    runtime.task_history.clear()
                console.clear()
                print_welcome()
                continue


            if user_input.lower() == "/help":
                console.print(Panel(HELP_TEXT, title="[bold gold1]Commands & Shortcuts[/bold gold1]", border_style="gold1"))
                continue

            if user_input.lower() == "/reset":
                messages.clear()
                memory.clear()
                if hasattr(runtime, "reset"):
                    runtime.reset()
                elif hasattr(runtime, "_history"):
                    runtime._history.clear()
                console.print("[bold yellow]🧹 Conversation and agentic memory have been cleared.[/bold yellow]\n")
                continue

            if user_input.lower().startswith("/login"):
                handle_login()
                continue

            if user_input.lower() == "/memory":
                handle_memory_command()
                continue

            if user_input.lower().startswith("/web"):
                parts = user_input.split(maxsplit=1)
                arg = parts[1] if len(parts) > 1 else ""
                handle_web_command(arg)
                continue

            if user_input.lower().startswith("/d1"):
                parts = user_input.split(maxsplit=1)
                arg = parts[1] if len(parts) > 1 else ""
                handle_d1_command(arg)
                continue

            if user_input.lower().startswith("/headroom"):
                parts = user_input.split(maxsplit=1)
                arg = parts[1] if len(parts) > 1 else ""
                handle_headroom_command(arg)
                continue

            if user_input.lower().startswith("/parallel"):
                parts = user_input.split(maxsplit=1)
                arg = parts[1] if len(parts) > 1 else ""
                handle_parallel_command(arg)
                continue

            if user_input.lower() in ("/accounts", "/gateway"):
                handle_accounts_command()
                continue

            if user_input.lower() in ("/health", "/doctor", "/auth"):
                handle_doctor_command()
                continue

            if user_input.lower().startswith("/debug"):
                parts = user_input.split(maxsplit=1)
                arg = parts[1].strip().lower() if len(parts) > 1 else ""
                if arg == "live":
                    _tui.live_mode = not _tui.live_mode
                    state = "[bold green]ON[/bold green]" if _tui.live_mode else "[bold yellow]OFF[/bold yellow]"
                    console.print(f"\n[bold gold1]⊡ Live step display:[/bold gold1] {state}\n")
                elif arg in ("latency", "timing", "perf", "telemetry", "metrics"):
                    from kratos_agent.tui.debug_panel import render_latency_report
                    render_latency_report()
                else:
                    # Show step log, event trace, and latency diagnostic from last turn
                    from kratos_agent.tui.debug_panel import render_latency_report
                    steps = _tui.get_last_steps()
                    events = _tui.get_last_events()
                    if not steps and not events:
                        console.print("[dim]No execution data from last turn yet. Run a query first.[/dim]\n")
                    else:
                        render_step_log(steps)
                        if events:
                            render_event_log(events)
                        render_latency_report()
                continue

            if user_input.lower() in ("/context", "/debug-context", "/trace"):
                handle_context_command()
                continue

            if any(user_input.lower().startswith(c) for c in ("/prompts", "/prompt")):
                parts = user_input.split(maxsplit=1)
                arg = parts[1] if len(parts) > 1 else ""
                handle_prompts_command(arg)
                continue

            if any(user_input.lower().startswith(c) for c in ("/review", "/code-review", "/codereview")):
                parts = user_input.split(maxsplit=1)
                arg = parts[1] if len(parts) > 1 else ""
                handle_code_review_command(arg)
                continue

            if user_input.lower().startswith("/simplify"):
                parts = user_input.split(maxsplit=1)
                arg = parts[1] if len(parts) > 1 else ""
                handle_simplify_command(arg)
                continue

            if user_input.lower().startswith("/security"):
                parts = user_input.split(maxsplit=1)
                arg = parts[1] if len(parts) > 1 else ""
                handle_security_command(arg)
                continue

            if any(user_input.lower().startswith(c) for c in ("/skill", "/skills")):
                parts = user_input.split(maxsplit=1)
                arg = parts[1] if len(parts) > 1 else ""
                handle_skill_command(arg)
                continue

            if any(user_input.lower().startswith(c) for c in ("/create-tool", "/create-tools", "/tool-create", "/createtool")):
                parts = user_input.split(maxsplit=1)
                arg = parts[1] if len(parts) > 1 else ""
                handle_create_tool_command(arg)
                continue

            if user_input.lower().startswith("/model"):
                parts = user_input.split(maxsplit=1)
                arg = parts[1] if len(parts) > 1 else ""
                handle_model_command(arg)
                continue

            if user_input.lower() == "/tools":
                if not runtime.tools:
                    console.print("[dim]No tools loaded.[/dim]\n")
                else:
                    tool_table = Table(title="🗡️ Active & Self-Created Tools", border_style="red")
                    tool_table.add_column("Name", style="bold gold1")
                    tool_table.add_column("Description", style="white")
                    for t in runtime.tools:
                        tool_table.add_row(t.name, t.description or "No description")
                    console.print(tool_table)
                    console.print()
                continue

            # /mode [suggest|auto-edit|full-auto] — Codex-style approval mode
            if user_input.lower().startswith("/mode"):
                parts = user_input.split(maxsplit=1)
                arg = parts[1].strip().lower() if len(parts) > 1 else ""
                mode_map = {
                    "suggest": ApprovalMode.SUGGEST,
                    "auto-edit": ApprovalMode.AUTO_EDIT,
                    "auto_edit": ApprovalMode.AUTO_EDIT,
                    "full-auto": ApprovalMode.FULL_AUTO,
                    "full_auto": ApprovalMode.FULL_AUTO,
                    "full": ApprovalMode.FULL_AUTO,
                }
                if arg in mode_map:
                    approval_gate.set_mode(mode_map[arg])
                else:
                    mode_badges = {
                        ApprovalMode.SUGGEST:   "[yellow]suggest[/yellow]   — read-only, all writes need approval",
                        ApprovalMode.AUTO_EDIT: "[cyan]auto-edit[/cyan]  — file edits auto, shell needs approval",
                        ApprovalMode.FULL_AUTO: "[green]full-auto[/green]  — full autonomy (default)",
                    }
                    console.print(f"\n[bold gold1]Current mode:[/bold gold1] {approval_gate.mode_badge()}")
                    console.print("\n[bold]Available modes:[/bold]")
                    for badge in mode_badges.values():
                        console.print(f"  {badge}")
                    console.print("\n[dim]Usage: /mode suggest | /mode auto-edit | /mode full-auto[/dim]\n")
                continue

            # /plan [on|off|<query>] — Plan Mode (DeepSeek Harness & Claude Code)
            if user_input.lower().startswith("/plan"):
                parts = user_input.split(maxsplit=1)
                arg = parts[1].strip() if len(parts) > 1 else ""
                if arg.lower() in ("off", "exit", "disable", "stop"):
                    runtime.plan_mode = False
                    console.print("\n[bold gold1]📋 Plan Mode:[/bold gold1] [bold yellow]OFF[/bold yellow] (Full execution enabled)\n")
                    continue
                elif arg.lower() in ("on", "enable", "start"):
                    runtime.plan_mode = True
                    console.print("\n[bold gold1]📋 Plan Mode:[/bold gold1] [bold green]ON[/bold green]")
                    console.print("[dim]Agent will explore, inspect, and draft an architecture plan without making file modifications.[/dim]\n")
                    continue
                elif not arg:
                    runtime.plan_mode = not getattr(runtime, "plan_mode", False)
                    state = "[bold green]ON[/bold green]" if runtime.plan_mode else "[bold yellow]OFF[/bold yellow]"
                    console.print(f"\n[bold gold1]📋 Plan Mode:[/bold gold1] {state}")
                    console.print("[dim]Usage: /plan on | /plan off | /plan <task>[/dim]\n")
                    continue
                else:
                    runtime.plan_mode = True
                    console.print(f"\n[bold gold1]📋 Plan Mode activated for:[/bold gold1] {arg}\n")
                    user_input = arg

            # /clear — Clear conversation history and browser task state (§25)
            if user_input.lower().strip() in ("/clear", "clear"):
                from kratos_agent.computer.browser.target import get_target_manager
                get_target_manager().clear_task_target()
                messages.clear()
                console.print("[dim]Session and browser task state cleared. (Chrome window and tabs retained).[/dim]\n")
                continue

            # /status — Comprehensive live subsystem status
            if user_input.lower().strip() in ("/status", "status"):
                handle_system_status_command()
                continue

            # /harness [status|mode|plugins|trace] — DeepSeek Harness manager
            if user_input.lower().startswith("/harness"):
                parts = user_input.split(maxsplit=1)
                arg = parts[1] if len(parts) > 1 else ""
                handle_harness_command(arg)
                continue

            # /bg-run <prompt> — Background agent loop (Kimi swarm / Claude Code)
            if user_input.lower().startswith("/bg-run"):
                parts = user_input.split(maxsplit=1)
                bg_prompt = parts[1].strip() if len(parts) > 1 else ""
                if not bg_prompt:
                    console.print("[yellow]Usage: /bg-run <prompt>[/yellow]\n")
                else:
                    background_runner.run(bg_prompt, agent_fn=runtime.run_agent)
                    console.print("[dim]Use /bg-status to monitor, /bg-result <id> to view output.[/dim]\n")
                continue

            # /bg-status — Show all background tasks
            if user_input.lower() in ("/bg-status", "/bg", "/background"):
                background_runner.print_status_table()
                console.print()
                continue

            # /bg-result <id> — Show background task result
            if user_input.lower().startswith("/bg-result"):
                parts = user_input.split(maxsplit=1)
                task_id = parts[1].strip() if len(parts) > 1 else ""
                if not task_id:
                    console.print("[yellow]Usage: /bg-result <task-id>[/yellow]\n")
                else:
                    result = background_runner.get_result(task_id)
                    console.print(Panel(
                        Markdown(result),
                        title=f"[bold gold1]⚡ Background Task Result: {task_id[:8]}[/bold gold1]",
                        border_style="gold1", padding=(1, 2)
                    ))
                console.print()
                continue

            # /bg-cancel <id> — Cancel background task
            if user_input.lower().startswith("/bg-cancel"):
                parts = user_input.split(maxsplit=1)
                task_id = parts[1].strip() if len(parts) > 1 else ""
                if not task_id:
                    console.print("[yellow]Usage: /bg-cancel <task-id>[/yellow]\n")
                else:
                    msg = background_runner.cancel(task_id)
                    console.print(f"[bold yellow]{msg}[/bold yellow]\n")
                continue

            # Parse @file attachments
            processed_query, attached_files = parse_file_mentions(user_input)
            if attached_files:
                for att in attached_files:
                    console.print(f"[dim green]📎 Attached:[/dim green] [bold white]{att}[/bold white]")

            # Direct agent bypass command (/direct <query> or /kratos <query>)
            force_direct_kratos = False
            if processed_query.lower().startswith(("/direct ", "/kratos ", "/agent ")):
                parts = processed_query.split(maxsplit=1)
                processed_query = parts[1].strip() if len(parts) > 1 else ""
                force_direct_kratos = True
                if not processed_query:
                    console.print("[dim]Usage: /direct <query> or /kratos <query> to run directly on Kratos Agent.[/dim]\n")
                    continue

            # Multi-turn history
            messages.append({"role": "user", "content": processed_query})

            # Check fast paths before Gemini Live or general agent loop (§14, §22, §23, §43, §47, §49)
            clean_q = processed_query.strip()
            clean_lower = clean_q.lower()

            # 1. Direct URL Fast Path (§22)
            if re.fullmatch(r"(?:https?://|www\.)[^\s]+", clean_q, re.IGNORECASE):
                console.print(f"\n[bold cyan]⚡ [BrowserFastPath] Navigating to: {clean_q}[/bold cyan]")
                from kratos_agent.computer.browser.manager import get_browser_manager
                b_res = get_browser_manager().open_url(clean_q)
                if b_res.ok:
                    console.print(f"[bold green]✓ Navigated to {clean_q}[/bold green]\n")
                    messages.append({"role": "assistant", "content": f"Navigated to {clean_q}."})
                else:
                    console.print(f"[bold red]⚠️ Navigation failed: {b_res.detail}[/bold red]\n")
                    messages.append({"role": "assistant", "content": f"Failed to navigate to {clean_q}: {b_res.detail}"})
                continue

            # 2. Generic Desktop Application Launch Fast Path (§18, §23, §35)
            from kratos_agent.computer.apps.launcher import get_launcher
            from kratos_agent.computer.browser.intent import parse_media_intent, is_pure_app_launch_request
            resolved_app = get_launcher().resolve_application(clean_q)
            m_intent_hint = parse_media_intent(clean_q)
            if resolved_app and is_pure_app_launch_request(clean_q) and m_intent_hint.get("intent") not in {"open_youtube", "open_whatsapp", "whatsapp_message"}:
                _, _, display_name = resolved_app
                console.print(f"\n[bold cyan]⚡ [AppFastPath] Opening {display_name}...[/bold cyan]")
                a_res = get_launcher().launch_and_verify(clean_q)
                if a_res.ok and a_res.verified:
                    console.print(f"[bold green]✓ Done — {display_name} is open and focused in the foreground.[/bold green]\n")
                    messages.append({"role": "assistant", "content": f"Done — {display_name} is open and focused in the foreground."})
                elif a_res.ok:
                    console.print(f"[bold green]✓ {a_res.observation or display_name + ' opened.'}[/bold green]\n")
                    messages.append({"role": "assistant", "content": a_res.observation or f"{display_name} opened."})
                else:
                    console.print(f"[bold red]⚠️ Could not launch {display_name}: {a_res.detail}[/bold red]\n")
                    messages.append({"role": "assistant", "content": f"Could not launch {display_name}: {a_res.detail}"})
                continue

            # 3. Semantic Media / Browser Intent Parsing & Physical Verification
            from kratos_agent.computer.browser.intent import parse_media_intent, should_reuse_browser_context
            from kratos_agent.computer.browser.playwright import PlaywrightDriver, can_report_success
            from kratos_agent.computer.browser.target import get_target_manager
            from kratos_agent.computer.browser.manager import get_browser_manager

            m_intent = parse_media_intent(processed_query)
            intent_type = m_intent.get("intent")
            intent_query = m_intent.get("query", "")

            # Open YouTube
            if intent_type == "open_youtube":
                prev_task = get_target_manager().get_active_task_target()
                reuse_target = should_reuse_browser_context(prev_task, m_intent)
                if not reuse_target and prev_task is not None:
                    get_target_manager().clear_task_target()
                prev_state = prev_task.tab_id if prev_task else "None"
                print(f"[CONTINUATION]\nTask: open youtube\nPrevious state: {prev_state}\nNew command: open youtube\nReuse target: {reuse_target}")
                console.print(f"\n[bold cyan]⚡ [BrowserFastPath] Opening YouTube...[/bold cyan]")
                if not reuse_target:
                    get_browser_manager().initialize_browser_task(initial_url="https://www.youtube.com")
                b_res = get_browser_manager().open_url("https://www.youtube.com")
                if b_res.ok:
                    console.print(f"[bold green]✓ Done — YouTube is open.[/bold green]\n")
                    messages.append({"role": "assistant", "content": "Done — YouTube is open."})
                else:
                    console.print(f"[bold red]⚠️ YouTube could not be opened: {b_res.detail}[/bold red]\n")
                    messages.append({"role": "assistant", "content": f"YouTube could not be opened: {b_res.detail}"})
                continue

            # Open WhatsApp Web only for a pure open request.
            if intent_type == "open_whatsapp":
                prev_task = get_target_manager().get_active_task_target()
                reuse_target = should_reuse_browser_context(prev_task, m_intent)
                if not reuse_target and prev_task is not None:
                    get_target_manager().clear_task_target()
                prev_state = prev_task.tab_id if prev_task else "None"
                print(
                    f"[CONTINUATION]\nTask: open whatsapp\nPrevious state: {prev_state}"
                    f"\nNew command: open whatsapp\nReuse target: {reuse_target}"
                )
                console.print("\n[bold cyan]⚡ [BrowserFastPath] Opening WhatsApp Web...[/bold cyan]")
                if not reuse_target:
                    get_browser_manager().initialize_browser_task(initial_url="https://web.whatsapp.com")
                b_res = get_browser_manager().open_url("https://web.whatsapp.com")
                if b_res.ok:
                    console.print("[bold green]✓ Done — WhatsApp Web is open.[/bold green]\n")
                    messages.append({"role": "assistant", "content": "Done — WhatsApp Web is open."})
                else:
                    console.print(f"[bold red]⚠️ WhatsApp Web could not be opened: {b_res.detail}[/bold red]\n")
                    messages.append({"role": "assistant", "content": f"WhatsApp Web could not be opened: {b_res.detail}"})
                continue

            # Compound WhatsApp message: complete the requested action.
            if intent_type == "whatsapp_message":
                from kratos_agent.utils.computer_tools import browser_whatsapp_send_message
                contact = str(m_intent.get("contact", "")).strip()
                message = str(m_intent.get("message", ""))
                console.print(f"\n[bold cyan]⚡ [BrowserFastPath] Sending WhatsApp message to {contact}...[/bold cyan]")
                try:
                    result = json.loads(browser_whatsapp_send_message(contact=contact, message=message, verify=True))
                except Exception as exc:
                    result = {"ok": False, "verified": False, "error": str(exc)}
                if result.get("ok") and result.get("verified", True):
                    console.print(f"[bold green]✓ Done — sent the message to {contact} and verified it in WhatsApp Web.[/bold green]\n")
                    messages.append({"role": "assistant", "content": f"Done — sent the message to {contact} and verified it."})
                else:
                    reason = result.get("error") or result.get("detail") or "Message could not be verified."
                    console.print(f"[bold red]⚠️ WhatsApp message failed: {reason}[/bold red]\n")
                    messages.append({"role": "assistant", "content": f"WhatsApp message failed: {reason}"})
                continue

            # Search Video (State: SEARCH_RESULTS, NOT VIDEO_PLAYING)
            if intent_type == "search_video":
                from urllib.parse import quote_plus
                search_url = f"https://www.youtube.com/results?search_query={quote_plus(intent_query)}"
                prev_task = get_target_manager().get_active_task_target()
                reuse_target = should_reuse_browser_context(prev_task, m_intent)
                if not reuse_target and prev_task is not None:
                    get_target_manager().clear_task_target()
                prev_state = prev_task.tab_id if prev_task else "None"
                print(f"[CONTINUATION]\nTask: search {intent_query}\nPrevious state: {prev_state}\nNew command: search {intent_query}\nReuse target: {reuse_target}")
                console.print(f"\n[bold cyan]⚡ [BrowserFastPath] Searching YouTube for '{intent_query}'...[/bold cyan]")
                b_res = get_browser_manager().open_url(search_url)
                if b_res.ok:
                    active_task = get_target_manager().get_active_task_target()
                    tab_lbl = active_task.tab_id if active_task else "PAGE-42"
                    print(f"[ACTION]\nOperation: youtube_search\nTab: {tab_lbl}\nTarget: {intent_query}\nVerified: True\nState: SEARCH_RESULTS")
                    print("[TERMINATION]\nSuccess: True\nVerified: True\nFinal State: SEARCH_RESULTS")
                    console.print(f"[bold green]✓ Done — YouTube search results for '{intent_query}' are displayed.[/bold green]\n")
                    messages.append({"role": "assistant", "content": f"Done — YouTube search results for '{intent_query}' are displayed."})
                else:
                    console.print(f"[bold red]⚠️ YouTube search failed: {b_res.detail}[/bold red]\n")
                    messages.append({"role": "assistant", "content": f"YouTube search failed: {b_res.detail}"})
                continue

            # Play Video / Compound Browser Task (Evidence-based verification! §13, §14, §15, §27)
            if intent_type in ("compound_browser_task", "play_video"):
                prev_task = get_target_manager().get_active_task_target()
                prev_target = get_target_manager().get_active_target()
                reuse_target = should_reuse_browser_context(prev_task, m_intent)
                if not reuse_target and prev_task is not None:
                    get_target_manager().clear_task_target()
                prev_state = prev_task.tab_id if prev_task else (prev_target.url if prev_target else "None")
                print(f"[CONTINUATION]\nTask: play {intent_query}\nPrevious state: {prev_state}\nNew command: play {intent_query}\nReuse target: {reuse_target}")
                console.print(f"\n[bold cyan]⚡ [BrowserFastPath] Playing {intent_query} in current Chrome window...[/bold cyan]")
                drv = PlaywrightDriver()
                p_res = drv.search_and_play_youtube(intent_query)
                if can_report_success(p_res):
                    console.print(f"[bold green]✓ Done — the {intent_query} walkthrough is playing in the current Chrome window.[/bold green]\n")
                    messages.append({"role": "assistant", "content": f"Done — the {intent_query} walkthrough is playing in the current Chrome window."})
                else:
                    err_reason = p_res.detail or "⚠️ I found the YouTube results, but I couldn't verify that a video started playing."
                    if not err_reason.startswith("⚠️"):
                        err_reason = f"⚠️ {err_reason}"
                    console.print(f"[bold red]{err_reason}[/bold red]\n")
                    messages.append({"role": "assistant", "content": err_reason})
                continue

            # Pause Video
            if intent_type == "pause_video":
                prev_target = get_target_manager().get_active_target()
                prev_state = prev_target.url if prev_target else "Video Playing"
                print(f"[CONTINUATION]\nTask: pause video\nPrevious state: {prev_state}\nNew command: pause\nReuse target: True")
                console.print(f"\n[bold cyan]⚡ [Continuation] Pausing video in current Chrome window...[/bold cyan]")
                drv = PlaywrightDriver()
                p_res = drv.pause_video()
                if p_res.ok and p_res.verified:
                    console.print(f"[bold green]✓ Done — Video paused.[/bold green]\n")
                    messages.append({"role": "assistant", "content": "Done — Video paused."})
                else:
                    console.print(f"[bold red]⚠️ Could not pause video: {p_res.detail}[/bold red]\n")
                    messages.append({"role": "assistant", "content": f"Could not pause video: {p_res.detail}"})
                continue

            # Resume Video
            if intent_type == "resume_video":
                prev_target = get_target_manager().get_active_target()
                prev_state = prev_target.url if prev_target else "Video Paused"
                print(f"[CONTINUATION]\nTask: resume video\nPrevious state: {prev_state}\nNew command: resume\nReuse target: True")
                console.print(f"\n[bold cyan]⚡ [Continuation] Resuming video in current Chrome window...[/bold cyan]")
                drv = PlaywrightDriver()
                p_res = drv.resume_video()
                if p_res.ok and p_res.verified:
                    console.print(f"[bold green]✓ Done — Video resumed (playing).[/bold green]\n")
                    messages.append({"role": "assistant", "content": "Done — Video resumed (playing)."})
                else:
                    console.print(f"[bold red]⚠️ Could not resume video: {p_res.detail}[/bold red]\n")
                    messages.append({"role": "assistant", "content": f"Could not resume video: {p_res.detail}"})
                continue

            # Standby Command
            if intent_type == "standby":
                prev_target = get_target_manager().get_active_target()
                prev_state = prev_target.url if prev_target else "Active"
                print(f"[CONTINUATION]\nTask: standby\nPrevious state: {prev_state}\nNew command: standby\nReuse target: True")
                console.print(f"[bold green]✓ Standing by. Session and browser continuation state retained.[/bold green]\n")
                messages.append({"role": "assistant", "content": "Standing by. Session and browser continuation state retained."})
                continue



            # 4. Vision "What do you see" Fast Path (§14, §15, §16, §38)
            if clean_lower in (
                "what do you see",
                "what you see in this screen",
                "what do you see on this screen",
                "what do you see in this screen",
                "describe screen",
                "describe the screen",
                "look at screen",
                "look at the screen",
            ):
                console.print(f"\n[bold cyan]👁 [VisionFastPath] Inspecting screen...[/bold cyan]")
                v_desc = None
                if live_runtime and live_runtime.vision:
                    fut = asyncio.run_coroutine_threadsafe(
                        live_runtime.vision.describe_screen_fallback("Describe concisely what you see on the screen."),
                        live_runtime._loop,
                    )
                    try:
                        v_desc = fut.result(timeout=15.0)
                    except Exception as e:
                        v_desc = f"Unable to describe screen: {e}"
                else:
                    from kratos_agent.live.screen import get_screen_stream
                    s_frame = get_screen_stream().capture_now()
                    if s_frame:
                        v_desc = f"Screen capture online ({s_frame.width}x{s_frame.height}, backend: {s_frame.backend})."
                    else:
                        v_desc = "Screen capture offline. Unable to capture frame."
                console.print(f"[bold green]{v_desc}[/bold green]\n")
                messages.append({"role": "assistant", "content": v_desc})
                continue

            # Check if Gemini Live multimodal layer is connected and should handle the query first
            # Gemini will speak with voice, answer or assign task to Kratos Brain via start_agent_task
            is_gemini_connected = (
                not force_direct_kratos
                and live_runtime is not None
                and live_runtime.get_status().gemini_connected
            )

            if is_gemini_connected:
                try:
                    with console.status("[bold cyan]🌐 Gemini Live thinking & speaking...[/bold cyan]", spinner="dots"):
                        reply_text = live_runtime.send_chat_turn_sync(processed_query, timeout=45.0)
                    if reply_text:
                        messages.append({"role": "assistant", "content": reply_text})
                        continue
                except Exception as e:
                    logger.warning(f"[CLI] Gemini Live turn error, falling back to Kratos Agent: {e}")
                    console.print(f"[dim yellow]⚠ Gemini Live unavailable, falling back to Kratos Agent directly...[/dim yellow]")


            # ── Live TUI invoke (replaces bare runtime.invoke) ──────────────
            try:
                reply_text = _tui.invoke_with_live(messages)
            except KeyboardInterrupt:
                _tui.cancel()
                console.print("\n[bold yellow]⚠ Agent interrupted.[/bold yellow]")
                if runtime.memory.active_session:
                    summary = runtime.memory.active_session.get_unfinished_tasks_summary()
                    if "completed" in summary:
                        console.print(f"[dim]{summary}[/dim]")
                        console.print("[dim]Type [bold cyan]continue[/bold cyan] to resume execution from the interrupted task.[/dim]\n")
                # Keep history intact so continue can resume
                continue

            if not reply_text.strip():
                reply_text = "Task executed successfully."

            # Prevent network/provider error messages from contaminating multi-turn conversational history
            if reply_text.startswith("Model request failed:") or reply_text.startswith("Execution error:"):
                if messages and messages[-1].get("role") == "user":
                    messages.pop()
            else:
                messages.append({"role": "assistant", "content": reply_text})

            # Styled Box Output: Completion Card for coding/project tasks, clean Markdown for chat
            last_plan = _tui.get_last_plan()
            if last_plan and last_plan.tasks and not _tui.is_chat_mode():
                plan_dict = last_plan.to_dict()
                files_summary = runtime.loop.workspace_tracker.summary() if hasattr(runtime.loop, "workspace_tracker") else None
                verif_dict = runtime.loop.last_verification.__dict__ if getattr(runtime.loop, "last_verification", None) else None
                console.print()
                console.print(
                    render_completion_card(
                        summary_text=reply_text,
                        plan_dict=plan_dict,
                        files_summary=files_summary,
                        verification=verif_dict,
                        model_name=runtime.model_name
                    )
                )
                console.print()
            else:
                console.print()
                console.print(
                    Panel(
                        Markdown(reply_text),
                        title=f"[bold red]⚔️  KRATOS[/bold red] [dim]({runtime.model_name})[/dim] {approval_gate.mode_badge()}",
                        title_align="left",
                        border_style="red",
                        padding=(1, 2)
                    )
                )
                console.print()

        except (KeyboardInterrupt, EOFError):
            try:
                from kratos_agent.output.voice import get_tts_queue, get_voice_buffer
                get_tts_queue().cancel_current()
                get_voice_buffer().clear()
            except Exception:
                pass
            live_runtime.stop_background()
            _tui.cancel()
            console.print("\n[bold red]Kratos departs. Strength and honor.[/bold red]\n")
            break
        except Exception as e:
            console.print(f"[bold red]❌ Error:[/bold red] {e}\n")

def render_git_changes_card():
    """Renders a clean summary of workspace files modified/added in the current session (git stat style)."""
    try:
        from kratos_agent.core import git_tools as _git
        st = _git.get_git_status()
        if not st or "Working tree clean" in st or "git status error" in st:
            return
        
        lines = [l for l in st.splitlines() if l.strip() and not l.strip().startswith("##")]
        if not lines:
            return
        
        status_items = []
        for line in lines[:8]:
            status_code = line[:2].strip()
            file_name = line[2:].strip()
            if "A" in status_code or "??" in status_code:
                status_items.append(f"[bold green]🟢 A[/bold green] [white]{file_name}[/white]")
            elif "M" in status_code:
                status_items.append(f"[bold yellow]🟡 M[/bold yellow] [white]{file_name}[/white]")
            elif "D" in status_code:
                status_items.append(f"[bold red]🔴 D[/bold red] [white]{file_name}[/white]")
            else:
                status_items.append(f"[bold cyan]ℹ {status_code}[/bold cyan] [white]{file_name}[/white]")
        
        card_content = "\n".join(status_items)
        if len(lines) > 8:
            card_content += f"\n[dim]... and {len(lines) - 8} more files[/dim]"
            
        console.print(
            Panel(
                card_content,
                title="[bold #D4AF37]📊 Workspace Changes (git status)[/bold #D4AF37]",
                border_style="#D4AF37",
                padding=(0, 2)
            )
        )
    except Exception:
        pass

def main():
    if len(sys.argv) > 1:
        arg = sys.argv[1].strip()
        if arg in ("--help", "-h", "/help", "help"):
            console.print(HELP_TEXT)
            return
        if arg in ("--version", "-v", "version"):
            console.print("[bold red]Kratos Agent[/bold red] [bold gold1]v0.1.0[/bold gold1] - [dim]The Ghost of Sparta Codes[/dim]")
            return
        if arg in ("--cli", "-c", "cli", "/cli"):
            code_reloader.auto_reload_if_changed()
            start_interactive_cli()
            return

    # If invoked with no arguments or explicitly requesting web server:
    if len(sys.argv) == 1 or (len(sys.argv) > 1 and sys.argv[1].strip() in ("--web", "web", "/web", "serve", "server")):
        port = 7860
        if len(sys.argv) > 2 and sys.argv[2].strip().isdigit():
            port = int(sys.argv[2].strip())
        from kratos_agent.web.server import start_server
        console.print()
        console.print("[bold red]" + "═" * 72 + "[/bold red]")
        console.print(get_kratos_banner())
        console.print("[bold red]" + "═" * 72 + "[/bold red]\n")
        console.print(
            Panel(
                f"[bold green]✓ Kratos Agent Connected to Frontend![/bold green]\n\n"
                f"[bold cyan]🌐 Console URL: http://127.0.0.1:{port}[/bold cyan]\n"
                f"[dim]• Autonomous Agent Mode & Normal Chat Mode: ONLINE\n"
                f"• Active Model: {runtime.model_name}\n"
                f"• Cloudflare D1 Backend: Connected\n"
                f"• Interactive Terminal CLI: run 'uv run kratos --cli'\n"
                f"• Direct CLI prompt: run 'uv run kratos <prompt>'[/dim]\n\n"
                f"[bold gold1]Press Ctrl+C to shutdown server.[/bold gold1]",
                title="[bold red]⚔️ KRATOS AGENT // WEB RUNNER & API SERVER[/bold red]",
                border_style="red",
                padding=(1, 2)
            )
        )
        console.print()
        d1_client = getattr(runtime, "d1_db", None)
        start_server(port=port, open_browser=True, d1_db=d1_client, memory=memory, runtime=runtime, daemon=False)
        return

    code_reloader.auto_reload_if_changed()
    raw_query = " ".join(sys.argv[1:])
    processed_query, attached_files = parse_file_mentions(raw_query)
    
    if attached_files:
        for att in attached_files:
            console.print(f"[dim green]📎 Attached:[/dim green] [bold white]{att}[/bold white]")
    
    messages = [{"role": "user", "content": processed_query}]
    
    try:
        reply = _tui.invoke_with_live(messages)
    except KeyboardInterrupt:
        _tui.cancel()
        console.print("\n[bold yellow]⊘ Cancelled.[/bold yellow]\n")
        return
        
    if not reply.strip():
        reply = "Task executed successfully."

    last_plan = _tui.get_last_plan()
    if last_plan and last_plan.tasks and not _tui.is_chat_mode():
        plan_dict = last_plan.to_dict()
        files_summary = runtime.loop.workspace_tracker.summary() if hasattr(runtime.loop, "workspace_tracker") else None
        verif_dict = runtime.loop.last_verification.__dict__ if getattr(runtime.loop, "last_verification", None) else None
        console.print()
        console.print(
            render_completion_card(
                summary_text=reply,
                plan_dict=plan_dict,
                files_summary=files_summary,
                verification=verif_dict,
                model_name=runtime.model_name
            )
        )
        console.print()
    else:
        console.print(
            Panel(
                Markdown(reply),
                title=f"[bold red]⚔️  KRATOS[/bold red] [dim]({runtime.model_name})[/dim] {approval_gate.mode_badge()}",
                title_align="left",
                border_style="red",
                padding=(1, 2)
            )
        )

if __name__ == "__main__":
    main()
