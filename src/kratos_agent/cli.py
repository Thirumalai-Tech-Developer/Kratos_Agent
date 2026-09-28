import json
import logging
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

from kratos_agent.core.memory import AgenticSession

logger = logging.getLogger(__name__)

# Ensure Windows terminal handles UTF-8 & emojis properly
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception as e:
        logger.debug("Failed to reconfigure stdio encoding: %s", e)

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from kratos_agent.core.approval_mode import ApprovalMode, approval_gate
from kratos_agent.core.background_runner import background_runner
from kratos_agent.core.compactor import compactor
from kratos_agent.core.memory import memory
from kratos_agent.core.prompt_library import prompt_library
from kratos_agent.core.reloader import code_reloader
from kratos_agent.main import runtime
from kratos_agent.tui import KratosLiveRenderer, render_completion_card
from kratos_agent.tui.debug_panel import render_event_log, render_step_log
from kratos_agent.utils.tool_creator import create_or_update_tool

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
        from pathlib import Path

        import climage
        img_path = Path("kratos_banner.png")
        if img_path.exists():
            # Generate terminal image string with climage
            output = climage.convert(str(img_path), is_unicode=True, is_truecolor=True, is_256color=False, width=65)
            # Use rich's Text to properly handle ANSI colors and unicode block chars in terminal
            from rich.text import Text
            return Text.from_ansi(output)
    except Exception as e:
        logger.debug("Failed to render banner image: %s", e)
    return ASCII_BANNER

HELP_TEXT = """
[bold gold1]Available CLI Commands:[/bold gold1]
  [bold cyan]/doctor[/bold cyan]                  - Run Kratos model connection & transport diagnostics (alias: /health)
  [bold cyan]/model[/bold cyan]                  - List Kratos models and their input modalities
  [bold cyan]/gateway[/bold cyan]                - View Kratos Gateway status & configuration (alias: /accounts)
  [bold cyan]/bypass[/bold cyan]                 - View / confirm autonomous bypass permissions status
  [bold cyan]/mode[/bold cyan] [dim][suggest|auto-edit|full-auto|sovereign][/dim] - Set Kratos approval mode
  [bold cyan]/plan[/bold cyan] [dim][on|off|<query>][/dim]           - Enter or exit Kratos Plan Mode
  [bold cyan]/harness[/bold cyan] [dim][status|mode|plugins|trace][/dim] - Kratos Harness presets & plugins manager
  [bold cyan]/mcp[/bold cyan] [dim][status|reload|import <config>][/dim] - Manage local MCP server connections
  [bold cyan]/session[/bold cyan] [dim][new|load|show|rm][/dim] - Manage isolated agentic memory sessions
  [bold cyan]/prompts[/bold cyan] [dim][query][/dim]        - Browse the project's engineering prompt library
  [bold cyan]/review[/bold cyan] [dim][target][/dim]         - Run multi-angle senior code review (alias: /code-review)
  [bold cyan]/simplify[/bold cyan] [dim][target][/dim]       - Run 4-angle code cleanup & refactoring sweep
  [bold cyan]/security[/bold cyan] [dim][target][/dim]       - Run high-confidence vulnerability & exploit audit
  [bold cyan]/skill[/bold cyan] [dim][add|list|show|rm][/dim] - Add, view, or manage skills from URL / Internet
  [bold cyan]/create-tool[/bold cyan] [dim][desc][/dim]    - Autonomously forge and hot-reload a new tool
  [bold cyan]/tools[/bold cyan]                   - Inspect all active & self-created tools (edit_file, grep, etc.)
  [bold cyan]/plugins[/bold cyan]                 - Inspect loaded harness plugins, state & services
  [bold cyan]/compact[/bold cyan]                 - Compress conversation context (alias: /compress)
  [bold cyan]/headroom[/bold cyan] [dim][on|off|status][/dim]  - Headroom context compression stats & toggle
  [bold cyan]/parallel[/bold cyan] [dim][on|off|status][/dim]  - Toggle or configure parallel tool & subagent execution
  [bold cyan]/reload[/bold cyan]                  - Live hot-reload all code, tools & skills (alias: /r)
  [bold cyan]/memory[/bold cyan]                  - View persistent agentic memory & command log
  [bold cyan]/web[/bold cyan] [dim][port][/dim]            - Launch interactive Cloudflare D1 Web Console & Trace viewer
  [bold cyan]/d1[/bold cyan]                     - Inspect Cloudflare D1 connection, database stats & diagnostics
  [bold cyan]/voice[/bold cyan] [dim][on|off][/dim]             - Toggle microphone voice input / mute
  [bold cyan]/vision[/bold cyan] [dim][camera|screen|both|off][/dim] - Control camera & screen capture vision
  [bold cyan]/live[/bold cyan] [dim][status|reconnect][/dim]        - Inspect or manage Gemini Live multimodal session
  [bold cyan]/search[/bold cyan] [dim][web|tools|memory|github] <q>[/dim] - Query unified search & retrieval fabric
  [bold cyan]/context[/bold cyan]                 - Inspect the redacted assembled request, tools, tokens and trace

  [bold cyan]/debug[/bold cyan]                   - Inspect full execution/event trace from last turn
  [bold cyan]/debug live[/bold cyan]              - Toggle live step display on/off
  [bold cyan]/reset[/bold cyan]                   - Reset multi-turn conversation memory
  [bold cyan]/clear[/bold cyan]                   - Clear the terminal screen
  [bold cyan]/help[/bold cyan]                    - Display this commands overview
  [bold cyan]/exit[/bold cyan]                    - Exit Kratos Agent (alias: /quit, Ctrl+C)

[bold gold1]Background Agent (Kratos):[/bold gold1]
  [bold cyan]/bg-run[/bold cyan] [dim]<prompt>[/dim]         - Launch a prompt as a background task (non-blocking)
  [bold cyan]/bg-status[/bold cyan]               - Show all background tasks and their status
  [bold cyan]/bg-result[/bold cyan] [dim]<id>[/dim]          - Show output of a completed background task
  [bold cyan]/bg-cancel[/bold cyan] [dim]<id>[/dim]          - Cancel a running background task

[bold gold1]Special Syntax & Autocomplete:[/bold gold1]
  [bold green]@<file>[/bold green]                - Type [bold green]@[/bold green] to autocomplete & attach local files
  [bold cyan]/<command>[/bold cyan]             - Type [bold cyan]/[/bold cyan] to see live command auto-suggestions (auto-fixes [dim]//[/dim])
"""

prompt_style = Style.from_dict({
    "prompt": "bold #FF4FA3",
    "arrow": "bold #42E8F5",
    # Autocompletion popup styling
    "completion-menu.completion": "bg:#171323 #DCE6F2",
    "completion-menu.completion.current": "bold bg:#A52B70 #FFFFFF",
    "completion-menu.meta.completion": "bg:#171323 #42C9D8 italic",
    "completion-menu.meta.completion.current": "bold bg:#6E2452 #FFFFFF",
    "scrollbar.background": "bg:#171323",
    "scrollbar.button": "bg:#FF4FA3",
})

def normalize_command(cmd_str: str) -> str:
    """Automatically detects and removes duplicate leading slashes (e.g. //help -> /help, ///review -> /review)."""
    cleaned = cmd_str.strip()
    if cleaned.startswith("/"):
        cleaned = "/" + cleaned.lstrip("/")
    return cleaned

class KratosCompleter(Completer):
    """Provides live autocomplete for commands and workspace files."""
    SLASH_COMMANDS = [
        ("/doctor", "Run Brain connection & transport diagnostics (alias: /health)"),
        ("/gateway", "View Brain Gateway status & configuration (alias: /accounts)"),
        ("/bypass", "View / confirm autonomous bypass permissions mode"),
        ("/session", "Manage isolated agentic memory sessions (new, load, list, show, rm)"),
        ("/model", "List Kratos models and their input modalities"),
        ("/prompts", "Browse the project's engineering prompt library"),
        ("/review", "Run senior multi-angle code review on changes"),
        ("/simplify", "Run 4-angle code cleanup and refactoring sweep"),
        ("/security", "Run security vulnerability & exploit audit"),
        ("/skill", "Inspect active skills and knowledge modules"),
        ("/skill add", "Install skill from URL or Internet (e.g. /skill add react-19)"),
        ("/skill show", "Show skill guidelines & cheatsheet (e.g. /skill show <name>)"),
        ("/skill remove", "Uninstall an active skill (e.g. /skill remove <name>)"),
        ("/create-tool", "Autonomously forge and hot-reload a new tool"),
        ("/tools", "Inspect active and self-created tools (edit_file, grep, etc.)"),
        ("/plugins", "Inspect loaded harness plugins, version, state and services"),
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
        ("/harness", "Kratos Harness status, preset mode, plugins & trace"),
        ("/harness status", "Inspect active preset, loaded plugins and health"),
        ("/harness mode", "Switch harness preset (standard, code, minimal, creator)"),
        ("/harness plugins", "List all registered and active harness plugins"),
        ("/harness trace", "View recent execution trace and audit replay"),
        ("/mcp", "Inspect connected MCP servers and tools"),
        ("/mcp import", "Import an MCP server configuration file"),
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

        # 1. Autocomplete for /skill subcommands and installed skill names
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
                except Exception as e:
                    logger.debug("Failed checking file for completer: %s", e)

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

    grid.add_row("⚔  Model", f"[bold cyan]{escape(runtime.model_name or 'UNCONFIGURED')}[/bold cyan] [dim](Kratos Gateway)[/dim]")
    grid.add_row("⛓  Mode", f"{mode_badge}  [dim]| /mode suggest|auto-edit|full-auto|sovereign[/dim]")
    grid.add_row("🔧  Tools", f"[bold green]{num_tools} loaded[/bold green]  [dim]{', '.join(loaded_tool_names[:5])}{'...' if num_tools > 5 else ''}[/dim]")
    grid.add_row("🧠  Skills", f"[bold green]{num_skills} active[/bold green]  [dim]Use /skill to view or add[/dim]")
    grid.add_row("📜  Memory", f"[dim]{mem_label}[/dim]")

    # Multimodal Perception Status (Voice + Hearing + Vision)
    try:
        from kratos_agent.live import get_live_runtime
        from kratos_agent.output.native_voice import get_native_voice
        _live_rt = get_live_runtime()
        _st = _live_rt.get_status()

        _mic_badge = "[bold green]ONLINE[/bold green]" if _st.microphone_active else "[dim]OFFLINE[/dim]"
        _cam_badge = "[bold green]ONLINE[/bold green]" if _st.camera_active else "[dim]OFFLINE[/dim]"
        _scr_badge = "[bold green]ONLINE[/bold green]" if _st.screen_active else "[dim]OFFLINE[/dim]"
        _voice_eng = get_native_voice()
        if _st.muted or (_voice_eng and _voice_eng.is_muted):
            _voice_badge = "[bold yellow]MUTED[/bold yellow]"
        elif _st.gemini_connected:
            _voice_badge = f"[bold green]ONLINE (Gemini Live: {_live_rt.config.voice_name})[/bold green]"
        else:
            _voice_badge = "[bold green]ONLINE (Native SAPI)[/bold green]"

        grid.add_row("🎤  Voice", f"{_voice_badge}  [dim]| /voice on|off|speak[/dim]")
        grid.add_row("👁  Vision", f"Screen: {_scr_badge}  Camera: {_cam_badge}  [dim]| /vision screen|camera|describe[/dim]")
    except Exception as e:
        logger.debug("Failed to populate live subsystem badges: %s", e)


    grid.add_row("⚡  Quick Start", "[bold gold1]/[/bold gold1] for commands  [bold gold1]/model[/bold gold1] to view the configured model  [bold green]@[/bold green] for files  [bold cyan]/bg-run[/bold cyan] background")

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

def parse_file_mentions(user_input: str) -> tuple[str, list[str]]:
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

def handle_login(arg: str = ""):
    """Show that Kratos uses its configured local model gateway."""
    console.print("\n[bold green]✓ Kratos Gateway Active[/bold green]")
    console.print("[dim]Reasoning requests go to the configured local Kratos gateway and model.[/dim]\n")


def handle_model_command(arg: str = ""):
    """List gateway model modalities while keeping runtime selection locked."""
    from kratos_agent.brain.config import get_default_model, get_model_catalog

    configured = get_default_model()
    if not configured:
        console.print("[bold red]No Kratos model is configured.[/bold red] Set KRATOS_MODEL to the exact ID served by the local gateway.\n")
        return
    if arg.strip() and arg.strip() != configured:
        console.print(f"[bold yellow]Kratos is locked to {configured}.[/bold yellow] Model switching is disabled.\n")
        return
    runtime.set_model(configured)

    catalog = get_model_catalog(timeout=0.75)
    active_entry = next((item for item in catalog if item["id"] == configured), None)
    active_modality = " + ".join(active_entry.get("modality_badges", [])) if active_entry else "Text 📝"
    if not active_modality:
        active_modality = "Text 📝"
    console.print(
        f"[bold cyan]Configured Kratos model:[/bold cyan] {escape(configured)} "
        f"({escape(active_modality)})"
    )

    apply_metadata = getattr(runtime, "apply_model_metadata", None)
    if active_entry and callable(apply_metadata):
        apply_metadata(active_entry)

    has_gateway_metadata = any(item.get("metadata_available") for item in catalog)
    if not has_gateway_metadata:
        console.print(
            "[dim]Gateway metadata is unavailable. Text is shown as the chat input; "
            "vision and token limits will appear when the gateway reports them.\n[/dim]"
        )
        return
    if not active_entry or not active_entry.get("metadata_available"):
        console.print("[dim]The gateway did not report metadata for the configured model.\n[/dim]")

    table = Table(title="Kratos Gateway Models", border_style="cyan")
    table.add_column("Model ID", style="white")
    table.add_column("Modalities", style="cyan")
    table.add_column("Context", style="green", justify="right")
    table.add_column("Max input", style="green", justify="right")
    table.add_column("Max output", style="green", justify="right")
    table.add_column("Effort", style="magenta")
    table.add_column("Runtime", style="yellow")
    for item in catalog:
        table.add_row(
            escape(item["id"]),
            " + ".join(item.get("modality_badges", [])) or "Unknown",
            f"{item['context_length']:,}" if item.get("context_length") else "Unknown",
            f"{item['max_input_tokens']:,}" if item.get("max_input_tokens") else "Unknown",
            f"{item['max_output_tokens']:,}" if item.get("max_output_tokens") else "Unknown",
            item.get("selected_effort") or "Default",
            "Configured" if item["id"] == configured else "Catalog only",
        )
    console.print(table)
    console.print("[dim]The highest advertised effort tier is selected automatically when the model provides effort_tiers.\n[/dim]")


def handle_memory_command(arg: str = ""):
    """Unified handler for agentic memory inspection, maintenance, and optimization."""
    arg_clean = arg.strip().lower()

    # 1. Memory Optimization & Maintenance
    if arg_clean in ("optimize", "maintain", "tune", "opt"):
        with console.status("[bold cyan]🧠 Running Memory Maintenance & Optimization Engine...[/bold cyan]", spinner="dots"):
            from kratos_agent.memory.maintenance import get_memory_optimizer
            report = get_memory_optimizer().run_maintenance()

        table = Table(title="⚡ Memory Maintenance & Optimization Report", border_style="#00ff9d")
        table.add_column("Optimization Metric", style="bold white", width=32)
        table.add_column("Result / Status", style="bold cyan")

        status_color = "#00ff9d" if report.health_score >= 85 else ("yellow" if report.health_score >= 65 else "red")
        table.add_row("Overall Memory Health", f"[{status_color}]{report.health_score:.1f}% ({report.health_status})[/{status_color}]")
        table.add_row("Execution Duration", f"{report.duration_ms:.1f} ms")
        table.add_row("Decayed Memories", f"{report.decayed_count} records updated")
        table.add_row("Pruned Stale/Low-Confidence", f"[yellow]{report.pruned_records_count} records purged[/yellow]")
        table.add_row("Deduplicated Facts", f"[green]{report.deduplicated_count} facts merged[/green]")
        table.add_row("Cross-Tier Synced to V2", f"[cyan]{report.synced_to_v2_count} facts mirrored[/cyan]")
        table.add_row("Cross-Tier Synced to Cognitive", f"[cyan]{report.synced_to_cognitive_count} facts mirrored[/cyan]")
        table.add_row("Cognitive Records Cleaned", f"{report.cognitive_records_pruned} scratchpads pruned")
        table.add_row("Session Outputs Trimmed", f"{report.tool_outputs_trimmed} traces compacted")
        table.add_row("Database Reclaimed", f"[bold #00ff9d]{report.db_reclaimed_bytes:,} bytes[/bold #00ff9d]")
        table.add_row("Active Retained Memories", f"[bold green]{report.retained_records_count} records[/bold green]")

        console.print()
        console.print(table)
        console.print("[dim]✓ Memory layers optimized, cross-tier synced, and hot-cache purged.[/dim]\n")
        return

    # 2. Cross-Tier Synchronization
    if arg_clean.startswith(("sync", "mirror")):
        with console.status("[bold cyan]🔄 Synchronizing Memory Tiers...[/bold cyan]", spinner="dots"):
            from kratos_agent.memory import get_memory_manager
            synced_v2, synced_cog = get_memory_manager().sync_tiers()
        console.print(f"\n[bold green]✓ Memory Tiers Synchronized:[/bold green] [cyan]{synced_v2} facts mirrored to V2[/cyan], [cyan]{synced_cog} facts mirrored to Cognitive[/cyan]\n")
        return

    # 3. Memory Export / Backup
    if arg_clean.startswith(("export", "backup")):
        parts = arg.split(maxsplit=1)
        export_target = parts[1].strip() if len(parts) > 1 else None
        from pathlib import Path
        from kratos_agent.memory import get_memory_manager
        target_path = Path(export_target) if export_target else None
        saved_path = get_memory_manager().export_memory(target_path)
        console.print(f"\n[bold green]✓ Memory exported successfully to:[/bold green] [cyan]{saved_path}[/cyan]\n")
        return

    # 4. Memory Import / Restore
    if arg_clean.startswith(("import", "restore")):
        parts = arg.split(maxsplit=1)
        if len(parts) < 2:
            console.print("\n[bold yellow]Usage:[/bold yellow] /memory import <file_path.json>\n")
            return
        import_path = parts[1].strip()
        from pathlib import Path
        from kratos_agent.memory import get_memory_manager
        p = Path(import_path)
        if not p.exists():
            console.print(f"\n[bold red]Error:[/bold red] Import file not found: [cyan]{import_path}[/cyan]\n")
            return
        count = get_memory_manager().import_memory(p)
        console.print(f"\n[bold green]✓ Imported and consolidated {count} memory records from:[/bold green] [cyan]{p}[/cyan]\n")
        return

    # 5. Memory Cleaning / Purging
    if arg_clean.startswith(("clean", "clear", "purge", "prune")):
        sub = arg_clean.split(maxsplit=1)[1] if " " in arg_clean else "working"
        if sub in ("working", "scratchpad"):
            from kratos_agent.core.cognitive_memory import cognitive_memory
            count = cognitive_memory.clear(memory_type="working")
            console.print(f"\n[bold green]✓ Cleared working memory scratchpads[/bold green] [dim]({count} records)[/dim]\n")
        elif sub in ("episodic", "history"):
            from kratos_agent.core.cognitive_memory import cognitive_memory
            count = cognitive_memory.clear(memory_type="episodic")
            console.print(f"\n[bold green]✓ Cleared episodic memory[/bold green] [dim]({count} records)[/dim]\n")
        elif sub in ("all", "everything"):
            from kratos_agent.core.cognitive_memory import cognitive_memory
            count = cognitive_memory.clear()
            console.print(f"\n[bold yellow]⚠ Cleared all cognitive memories[/bold yellow] [dim]({count} records)[/dim]\n")
        else:
            console.print(f"\n[bold yellow]Usage:[/bold yellow] /memory clean working | /memory clean episodic | /memory clean all\n")
        return

    # 6. Memory Recall / Search
    if arg_clean.startswith(("recall", "search", "query", "find")):
        query_text = arg.split(maxsplit=1)[1].strip() if " " in arg else ""
        if not query_text:
            console.print("[bold yellow]Usage:[/bold yellow] /memory recall <query text>\n")
            return
        from kratos_agent.memory import get_memory_manager
        records = get_memory_manager().recall(query_text, limit=6)
        if not records:
            console.print(f"\n[dim]No memory records found matching:[/dim] [cyan]{query_text}[/cyan]\n")
            return
        table = Table(title=f"🔍 Recalled Memories for: '{query_text}'", border_style="cyan")
        table.add_column("Layer", style="bold gold1", width=14)
        table.add_column("Confidence", style="bold green", width=12)
        table.add_column("Content", style="white")
        for r in records:
            layer_name = r.layer.value.upper() if hasattr(r.layer, "value") else str(r.layer).upper()
            table.add_row(layer_name, f"{r.confidence:.2f}", r.content)
        console.print()
        console.print(table)
        console.print()
        return

    # 7. Default: Rich Memory Dashboard
    from kratos_agent.core.cognitive_memory import cognitive_memory
    from kratos_agent.memory import get_memory_manager

    cog_summary = cognitive_memory.get_summary()
    mgr = get_memory_manager()
    v2_records = mgr.store.list_records()
    health = mgr.get_health_metrics()

    health_score = health.get("health_score", 100.0)
    health_status = health.get("health_status", "OPTIMAL")
    status_color = "#00ff9d" if health_score >= 85 else ("yellow" if health_score >= 65 else "red")
    cache_stats = health.get("cache", {})

    table = Table(
        title=f"🧠 Kratos Agentic Memory Architecture  ·  [{status_color}]Health: {health_score:.1f}% ({health_status})[/{status_color}]",
        border_style="gold1"
    )
    table.add_column("Memory Layer", style="bold gold1", width=22)
    table.add_column("Type / Scope", style="white", width=26)
    table.add_column("Records", style="bold cyan", width=12)
    table.add_column("Decay Policy", style="dim white", width=22)

    table.add_row("📚 Semantic", "Project Facts & Architecture", str(cog_summary.get("semantic", 0)), "0.1% / day (slow)")
    table.add_row("⚙️ Procedural", "Workflows & Playbooks", str(cog_summary.get("procedural", 0)), "0.5% / day (medium)")
    table.add_row("📜 Episodic", "Past Session Experience", str(cog_summary.get("episodic", 0)), "5.0% / day (fast)")
    table.add_row("🧠 Working", "Active Session Scratchpad", str(cog_summary.get("working", 0)), "50.0% / day (rapid)")
    table.add_row("📦 Memory V2 Store", ".kratos/memory_v2.json", str(len(v2_records)), "Layer-adaptive")

    console.print()
    console.print(table)

    d1_stats = runtime.d1_db.get_stats()
    mode_text = "[bold green]Cloudflare D1 (Cloud)[/bold green]" if d1_stats.get("is_remote") else "[bold yellow]Local SQLite Mirror (.kratos/kratos_d1.db)[/bold yellow]"
    console.print(f"[dim]• Database: {mode_text} | Sessions: {d1_stats.get('sessions_count', 0)} | Turns: {d1_stats.get('turns_count', 0)}[/dim]")
    console.print(f"[dim]• Hot-Cache: Hit Rate: {cache_stats.get('hit_rate_pct', 0.0)}% | Active Cache: {cache_stats.get('cache_size', 0)}/{cache_stats.get('cache_max', 128)} entries[/dim]")
    console.print("[dim]• Commands: [bold gold1]/memory optimize[/bold gold1] | [bold gold1]/memory sync[/bold gold1] | [bold gold1]/memory clean[/bold gold1] | [bold gold1]/memory recall <query>[/bold gold1] | [bold gold1]/memory export[/bold gold1][/dim]\n")


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
                    title="[bold gold1]⚡ KRATOS HARNESS PRESET ACTIVE[/bold gold1]",
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

        table = Table(title="🔌 Kratos Harness Plugins", border_style="gold1")
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

        table = Table(title=f"📜 Kratos Harness Audit Trace (Last {len(events)} Events)", border_style="gold1")
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
            title="[bold gold1]⚡ KRATOS HARNESS RUNTIME KERNEL[/bold gold1]",
            border_style="gold1",
            padding=(1, 2)
        )
    )
    console.print("[dim]Subcommands: /harness mode <standard|code|minimal|creator> | /harness plugins | /harness trace [limit][/dim]\n")


def handle_mcp_command(arg: str = ""):
    """Inspect and manage MCP servers configured directly for Kratos."""
    parts = arg.strip().split(maxsplit=1)
    subcmd = parts[0].lower() if parts else "status"
    target = parts[1].strip() if len(parts) > 1 else ""
    if subcmd in {"import", "add"}:
        if not target:
            console.print("[yellow]Usage: /mcp import <path-to-mcp-config.json>[/yellow]\n")
            return
        try:
            count = runtime.mcp.add_import(target)
            runtime.reload_tools()
        except Exception as exc:
            console.print(f"[bold red]Import failed:[/bold red] {type(exc).__name__}: {exc}\n")
            return
        console.print(f"[green]Imported MCP config. {count} server(s) are now configured for Kratos.[/green]\n")
        return
    if subcmd in {"reload", "refresh"}:
        runtime.reload_tools()
        console.print("[green]MCP server configuration reloaded.[/green]\n")
        return

    mcp_table = Table(title="Configured MCP Servers", border_style="cyan")
    mcp_table.add_column("Server", style="bold gold1")
    mcp_table.add_column("Transport", style="cyan")
    mcp_table.add_column("State", style="white")
    mcp_table.add_column("Tools", justify="right")
    mcp_table.add_column("Error", style="red")
    for name, server in runtime.mcp.servers.items():
        state = runtime.mcp.status.get(name, {})
        mcp_table.add_row(name, server.transport or ("stdio" if server.command else "HTTP"), state.get("state", "not connected"), str(state.get("tools", 0)), state.get("error", ""))
    if not runtime.mcp.servers:
        console.print("[dim]No MCP servers configured.[/dim]")
    else:
        console.print(mcp_table)
    console.print("[dim]Use /mcp import <path-to-config.json> to add a local MCP server configuration.[/dim]\n")


def handle_accounts_command():
    """Displays the configured Kratos gateway and reasoning model."""
    from kratos_agent.brain import (
        get_base_url,
        get_default_model,
        get_endpoint_url,
        get_max_retries,
        get_request_timeout,
    )
    base_url = get_base_url()
    endpoint = get_endpoint_url()

    table = Table(title="⚔ Kratos Gateway Configuration", border_style="gold1")
    table.add_column("Property", style="bold cyan", width=22)
    table.add_column("Value / Details", style="white")

    table.add_row("Base URL", base_url)
    table.add_row("Chat Endpoint", endpoint)
    table.add_row("Kratos model", get_default_model() or "UNCONFIGURED")
    table.add_row("Request Timeout", f"{get_request_timeout()}s")
    table.add_row("Max Retries", str(get_max_retries()))
    table.add_row("Proxy Bypass", "[bold green]trust_env = False (Active)[/bold green]")
    table.add_row("Model policy", "Single configured model; no model switching or provider fallback")

    console.print(table)
    console.print()


def handle_system_status_command():
    """Print truthful live status, including the latest model and task failures."""
    from kratos_agent.ccs import get_capability_map
    from kratos_agent.core.latency_tracker import latency_tracker
    from kratos_agent.live import get_live_runtime

    table = Table(title="⚔  KRATOS STATUS", border_style="red")
    table.add_column("Subsystem", style="bold gold1", width=18)
    table.add_column("Status / Details", style="white")

    # A configured model is not proof that the chat endpoint accepts requests.
    metrics = latency_tracker.get_last_metrics()
    recorded_metrics = latency_tracker.get_all_metrics()
    if metrics is None:
        brain_state = "CONFIGURED · no chat request verified yet"
    elif metrics not in recorded_metrics:
        brain_state = f"REQUEST IN PROGRESS · {metrics.model or runtime.model_name}"
    elif metrics.status == "completed":
        brain_state = f"LAST REQUEST OK · {metrics.model or runtime.model_name} · {metrics.total_ms / 1000:.1f}s"
    else:
        from kratos_agent.output.voice import sanitize_speech_text
        failure = sanitize_speech_text(metrics.error or "Provider request failed")
        brain_state = f"LAST REQUEST FAILED · {metrics.model or runtime.model_name} · {failure}"
    table.add_row("Brain", escape(brain_state))

    # Mode
    table.add_row("Mode", f"[bold cyan]{escape(approval_gate.mode.value.upper())}[/bold cyan] approval mode")

    # Tools
    num_tools = len(runtime.tools)
    table.add_row("Tools", f"{num_tools} handlers registered")

    # CCS
    try:
        caps = get_capability_map()
        feature_flags = [value for value in caps.values() if isinstance(value, bool)]
        avail_caps = sum(feature_flags)
        table.add_row("CCS", f"{avail_caps}/{len(feature_flags)} detected feature flags are available")
    except Exception as exc:
        table.add_row("CCS", f"Unavailable: {escape(type(exc).__name__)}")

    # Displays
    try:
        from kratos_agent.ccs import get_computer_controller
        displays = get_computer_controller().get_displays()
        disp_str = " · ".join(f"[{d.index}] {d.width}x{d.height} @{d.scale_factor} {'primary' if d.is_primary else ''}".strip() for d in displays)
        table.add_row("Displays", disp_str or "Default Display")
    except Exception as exc:
        table.add_row("Displays", f"Unavailable: {escape(type(exc).__name__)}")

    # Voice / Vision / Gemini Live
    try:
        live_rt = get_live_runtime()
        st = live_rt.get_status()
        live_state = "CONNECTED" if st.gemini_connected else (st.live_health or "OFFLINE").upper()
        mic_state = "muted" if st.muted else ("active" if st.microphone_active else "inactive")
        table.add_row("Gemini Live", f"{escape(live_state)} · microphone {mic_state} · speaker {'active' if st.speaker_active else 'inactive'}")
        table.add_row("Voice", f"{'MUTED' if st.muted else 'ONLINE (Native SAPI TTS)'} · mic {mic_state}")
        table.add_row("Vision", f"screen {'ON' if st.screen_active else 'OFF'} · camera {'ON' if st.camera_active else 'OFF'} · analysis uses configured Kratos model")
        if st.last_error:
            table.add_row("Live error", escape(st.last_error))
    except Exception as exc:
        table.add_row("Gemini Live", f"Unavailable: {escape(type(exc).__name__)}")
        table.add_row("Voice", f"Unavailable: {escape(type(exc).__name__)}")
        table.add_row("Vision", "Unavailable")

    console.print()
    console.print(table)
    console.print()


def handle_health_command():
    """Displays local Brain engine health status."""
    handle_doctor_command()


def handle_doctor_command():
    """Runs a full diagnostic on Brain gateway connection, model configuration, and transport health."""
    import requests

    from kratos_agent.brain import (
        authenticate,
        get_base_url,
        get_endpoint_url,
        get_request_timeout,
    )

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
            table.add_row("Test Completion", "[bold red]✗ Failed (HTTP 404 Not Found)[/bold red]")
        else:
            error_msg = f"HTTP {res.status_code}: {res.text[:200]}"
            table.add_row("Gateway Connection", f"[yellow]⚠ Returned HTTP {res.status_code}[/yellow]")
            table.add_row("Test Completion", f"[yellow]⚠ Failed ({error_msg})[/yellow]")
    except requests.exceptions.ConnectionError:
        table.add_row("Gateway Connection", f"[bold red]✗ Unreachable (Connection refused on {base_url})[/bold red]")
        table.add_row("Test Completion", "[dim]Skipped[/dim]")
        error_msg = f"Brain LLM is not running on {base_url}. Please ensure Brain gateway is active on port 20128."
    except requests.exceptions.Timeout:
        table.add_row("Gateway Connection", "[bold yellow]⚠ Timeout (No response within 15s)[/bold yellow]")
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
            f"• [dim]Make sure the Kratos gateway is running at {base_url}.[/dim]",
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
        reply = runtime.brain.generate(
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
            parameters_schema=params,
            author_model=getattr(runtime, "model_name", "kratos"),
            trigger_prompt=user_prompt,
        )

        if "successfully created" not in result.lower():
            console.print(f"\n[bold red]❌ Tool forging rejected:[/bold red] {result}\n")
            return

        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold gold1")
        table.add_column(style="white")
        table.add_row("Tool Name:", f"[bold cyan]{tool_name}[/bold cyan]")
        table.add_row("Description:", description)
        table.add_row("Status:", "[bold green]Active & Hot-Loaded into Memory[/bold green]")
        table.add_row("Command:", "[dim]Available in /tools or by asking Kratos directly[/dim]")

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
                except Exception as e:
                    logger.warning("Failed loading session %s: %s", sid, e)
        
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
    """Browses, searches, or views reusable coding prompts and subagent instructions."""
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

    table = Table(title=f"📜 Coding Prompts ({len(prompt_library.prompts)} Indexed)", border_style="gold1")
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
    console.print(f"\n[bold gold1]🔍 Launching Kratos Senior Review on {target_desc}...[/bold gold1]\n")
    
    subagent_prompt = prompt_library.get_subagent_prompt("code_review")
    query = f"""Execute a thorough senior code review using a 5-angle review protocol (line-by-line correctness, removed behavior, cross-file caller trace, language pitfalls, edge cases).
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
    console.print(f"\n[bold gold1]✨ Launching Kratos 4-Angle Simplification on {target_desc}...[/bold gold1]\n")
    
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
    console.print(f"\n[bold gold1]🛡️  Launching Kratos Security Vulnerability Review on {target_desc}...[/bold gold1]\n")
    
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

def handle_compact_command(messages: list[dict[str, str]]) -> list[dict[str, str]]:
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

    from kratos_agent.brain.config import (
        get_max_parallel_workers,
        is_parallel_execution_enabled,
    )

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
    try:
        session = PromptSession(
            completer=KratosCompleter(),
            complete_while_typing=True,
            style=prompt_style
        )
    except Exception:
        session = None

    # Every interactive CLI launch starts a new conversational/task session.
    # Older sessions remain available explicitly via /session load.
    try:
        fresh_session = memory.create_session(
            title=f"CLI {time.strftime('%Y-%m-%d %H:%M:%S')}",
            model=runtime.model_name,
        )
        runtime.activate_session()
        console.print(f"[dim]🧼 Fresh session started: {fresh_session.session_id}[/dim]")
    except Exception as exc:
        console.print(f"[dim yellow]⚠ Could not create a fresh session; continuing with current runtime: {exc}[/dim yellow]")

    from kratos_agent.live import get_live_runtime
    live_runtime = get_live_runtime()

    def _on_live_user_speech(text: str) -> None:
        console.print(f"\n[bold green]🎤 [Voice] You:[/bold green] {escape(text)}")

        def _run_voice_request() -> None:
            try:
                reply = runtime.run_agent(text)
                console.print(Panel(Markdown(reply), title="[bold cyan]KRATOS · Voice Request[/bold cyan]", border_style="cyan"))
            except Exception as exc:
                logger.exception("Voice request failed")
                console.print(f"[bold red]Voice request failed:[/bold red] {escape(str(exc))}")

        threading.Thread(target=_run_voice_request, daemon=True, name="kratos-voice-request").start()

    def _on_live_model_speech(text: str) -> None:
        console.print(f"[bold cyan]⚡ [Voice] Kratos:[/bold cyan] {escape(text)}\n")

    live_runtime.on_user_transcript = _on_live_user_speech
    live_runtime.session.on_model_transcript = _on_live_model_speech
    live_runtime.start_in_background()

    print_welcome()
    
    messages: list[dict[str, str]] = []

    while True:
        try:
            # 1. Auto hot-reload if any source files or skills changed on disk
            code_reloader.auto_reload_if_changed()

            if session is not None:
                user_input = session.prompt(
                    HTML("<prompt>KRATOS</prompt> <arrow>›</arrow> ")
                ).strip()
            else:
                user_input = input("KRATOS › ").strip()

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
                arg = parts[1].strip() if len(parts) > 1 else ""
                arg_lower = arg.lower()
                from kratos_agent.output.native_voice import get_native_voice
                voice_eng = get_native_voice()
                if arg_lower.startswith("speak ") or arg_lower.startswith("say "):
                    text_to_speak = arg.split(maxsplit=1)[1].strip()
                    voice_eng.speak(text_to_speak)
                    console.print(f"\n[bold green]🔊 Speaking:[/bold green] [white]{text_to_speak}[/white]\n")
                elif arg_lower in ("devices", "list", "mics"):
                    devs = live_runtime.get_input_devices()
                    active_mic = live_runtime.get_active_microphone_name()
                    console.print(f"\n[bold cyan]🎤 Available Microphones ({len(devs)} detected):[/bold cyan]")
                    for d in devs:
                        prefix = "[bold green]▶ [/bold green]" if (d["name"] == active_mic or d.get("is_default")) else "  "
                        console.print(f"  {prefix}[bold white][{d['index']}][/bold white] {d['name']} [dim]({d.get('hostapi', '')}, {d.get('channels', 1)}ch)[/dim]")
                    console.print(f"[dim]Active: {active_mic}. Set via KRATOS_MIC_DEVICE=<index|name>[/dim]\n")
                elif arg_lower.startswith("device ") or arg_lower.startswith("set ") or arg_lower.startswith("select "):
                    target = arg.split(maxsplit=1)[1].strip()
                    new_name = live_runtime.set_microphone_device(target)
                    console.print(f"\n[bold green]🎤 Microphone switched to:[/bold green] [bold white]{new_name}[/bold white]\n")
                elif arg_lower.isdigit() and len(arg_lower) <= 2:
                    new_name = live_runtime.set_microphone_device(int(arg_lower))
                    console.print(f"\n[bold green]🎤 Microphone switched to:[/bold green] [bold white]{new_name}[/bold white]\n")
                elif arg_lower in ("off", "mute", "disable", "0"):
                    live_runtime.mute()
                    voice_eng.mute()
                    console.print("\n[bold yellow]🎤 Voice input and speech output muted.[/bold yellow]\n")
                elif arg_lower in ("on", "unmute", "enable", "1"):
                    live_runtime.unmute()
                    voice_eng.unmute()
                    voice_eng.speak("Voice enabled.")
                    console.print("\n[bold green]🎤 Voice active (unmuted & speaking enabled).[/bold green]\n")
                else:
                    if voice_eng.is_muted:
                        live_runtime.unmute()
                        voice_eng.unmute()
                        voice_eng.speak("Voice unmuted.")
                        console.print("\n[bold green]🎤 Voice active (unmuted & speaking enabled).[/bold green]\n")
                    else:
                        live_runtime.mute()
                        voice_eng.mute()
                        console.print("\n[bold yellow]🎤 Voice muted.[/bold yellow]\n")
                continue

            if user_input.lower().startswith("/vision"):
                parts = user_input.split(maxsplit=1)
                arg_raw = parts[1].strip() if len(parts) > 1 else ""
                arg_lower = arg_raw.lower()
                import asyncio

                if arg_lower.startswith(("describe", "analyze", "look", "see", "capture", "check")):
                    prompt = "Describe what is currently visible on the screen in detail and note any key elements or errors."
                    if " " in arg_raw:
                        prompt = arg_raw.split(maxsplit=1)[1].strip()
                    with console.status("[bold cyan]👁 Analyzing screen with the configured Kratos model...[/bold cyan]", spinner="dots"):
                        fut = asyncio.run_coroutine_threadsafe(
                            live_runtime.vision.analyze_vision(prompt=prompt, source="screen"),
                            live_runtime._loop,
                        )
                        try:
                            v_reply = fut.result(timeout=60.0)
                        except Exception as e:
                            v_reply = f"Vision error: {e}"
                    console.print(Panel(v_reply, title="[bold cyan]👁 Kratos Screen Analysis[/bold cyan]", border_style="cyan"))
                    continue

                if not arg_raw:
                    st = live_runtime.get_status()
                    console.print(f"\n[bold gold1]👁 Vision mode:[/bold gold1] [bold cyan]{st.video_mode.upper()}[/bold cyan] (camera: {st.camera_active}, screen: {st.screen_active})")
                    console.print("[dim]Usage: /vision describe [prompt] | /vision camera | /vision screen | /vision both | /vision off[/dim]\n")
                    continue

                arg_words = arg_raw.split()
                mode_candidate = arg_words[0].lower()
                valid_modes = {"camera", "cam", "screen", "desktop", "both", "all", "off", "none", "disable"}

                if mode_candidate not in valid_modes or len(arg_words) > 1:
                    bad_mode = mode_candidate if mode_candidate not in valid_modes else arg_raw
                    console.print(f"\n[bold red]Invalid /vision mode: {bad_mode}[/bold red]")
                    console.print("Usage: /vision describe [prompt] | /vision camera | /vision screen | /vision both | /vision off\n")
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

                from kratos_agent.retrieval import RetrievalQuery, get_retrieval_router
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
                        console.print("\n[bold green]🧠 Retrieved Context:[/bold green]")
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
                    from kratos_agent.computer.browser.manager import (
                        get_browser_manager,
                    )
                    from kratos_agent.core.error_pipeline import get_error_pipeline
                    from kratos_agent.live.screen import get_screen_stream
                    s_health = get_screen_stream().health_check()
                    b_diag = get_browser_manager().diagnostics()
                    st = live_runtime.get_status() if live_runtime else None
                    pipe = get_error_pipeline()
                    recent_errs = pipe.get_recent_errors()

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

            if user_input.lower() == "/plugins":
                if not hasattr(runtime, "harness") or not runtime.harness:
                    console.print("[dim]Harness kernel is not active in current runtime.[/dim]\n")
                else:
                    plugins = runtime.harness.list_plugins()
                    if not plugins:
                        console.print("[dim]No harness plugins registered.[/dim]\n")
                    else:
                        table = Table(title="🔌 Harness Plugins", border_style="cyan")
                        table.add_column("Plugin", style="bold gold1")
                        table.add_column("Version", style="dim")
                        table.add_column("State", style="bold")
                        table.add_column("Services (Req → Prov)", style="white")
                        table.add_column("Status / Error", style="dim")

                        state_styles = {
                            "enabled": "[bold green]ENABLED[/bold green]",
                            "failed": "[bold red]FAILED[/bold red]",
                            "error": "[bold red]ERROR[/bold red]",
                            "disabled": "[yellow]DISABLED[/yellow]",
                            "loaded": "[cyan]LOADED[/cyan]",
                            "unloaded": "[dim]UNLOADED[/dim]",
                        }

                        for p in plugins:
                            st = state_styles.get(p.get("state", "").lower(), p.get("state", ""))
                            req = ", ".join(p.get("required_services", [])) or "none"
                            prov = ", ".join(p.get("provides_services", [])) or "none"
                            services_str = f"{req} → {prov}"
                            err = f"[red]{p.get('error')}[/red]" if p.get("error") else "[green]healthy[/green]"
                            table.add_row(
                                p.get("name", "unknown"),
                                p.get("version", "1.0.0"),
                                st,
                                services_str,
                                err,
                            )
                        console.print(table)
                        console.print()
                continue

            # /mode [suggest|auto-edit|full-auto] — Kratos approval mode
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
                    "sovereign": ApprovalMode.SOVEREIGN,
                    "jarvis": ApprovalMode.SOVEREIGN,
                }
                if arg in mode_map:
                    approval_gate.set_mode(mode_map[arg])
                else:
                    mode_badges = {
                        ApprovalMode.SUGGEST:   "[yellow]suggest[/yellow]   — read-only, all writes need approval",
                        ApprovalMode.AUTO_EDIT: "[cyan]auto-edit[/cyan]  — file edits auto, shell needs approval",
                        ApprovalMode.FULL_AUTO: "[green]full-auto[/green]  — full autonomy",
                        ApprovalMode.SOVEREIGN: "[bold magenta]sovereign[/bold magenta] — no app-level approval prompts",
                    }
                    console.print(f"\n[bold gold1]Current mode:[/bold gold1] {approval_gate.mode_badge()}")
                    console.print("\n[bold]Available modes:[/bold]")
                    for badge in mode_badges.values():
                        console.print(f"  {badge}")
                    console.print("\n[dim]Usage: /mode suggest | /mode auto-edit | /mode full-auto | /mode sovereign[/dim]\n")
                continue

            # /plan [on|off|<query>] — Kratos Plan Mode
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

            # /harness [status|mode|plugins|trace] — Kratos Harness manager
            if user_input.lower().startswith("/harness"):
                parts = user_input.split(maxsplit=1)
                arg = parts[1] if len(parts) > 1 else ""
                handle_harness_command(arg)
                continue

            # /mcp manages local MCP server configuration and status.
            if user_input.lower() == "/mcp" or user_input.lower().startswith("/mcp "):
                parts = user_input.split(maxsplit=1)
                arg = parts[1] if len(parts) > 1 else ""
                handle_mcp_command(arg)
                continue

            # /bg-run <prompt> — Background Kratos agent task
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

            # Safeguard: Slash commands (/...) are strictly for settings, options, and utilities.
            # They must NEVER fall through to trigger the agent loop or waste tokens.
            if user_input.startswith("/") and not user_input.lower().startswith(("/direct ", "/kratos ", "/agent ")):
                cmd_name = user_input.split()[0]
                console.print(f"\n[bold yellow]⚠ Unknown or unhandled slash command: {cmd_name}[/bold yellow]")
                console.print("[dim]Type /help to see all available commands.[/dim]\n")
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

            # Multi-turn history with multimodal image support
            image_attachments = [
                f for f in attached_files
                if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")) and os.path.exists(f)
            ]
            if image_attachments:
                import base64
                user_content: list[dict[str, Any]] = [{"type": "text", "text": processed_query}]
                for img_path in image_attachments:
                    try:
                        with open(img_path, "rb") as f_img:
                            b64_data = base64.b64encode(f_img.read()).decode("utf-8")
                            ext = img_path.rsplit(".", 1)[-1].lower()
                            mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
                            user_content.append({
                                "type": "image_url",
                                "image_url": {"url": f"data:{mime};base64,{b64_data}"}
                            })
                    except Exception as e:
                        console.print(f"[dim red]Failed to load image {img_path}: {e}[/dim red]")
                messages.append({"role": "user", "content": user_content})
            else:
                messages.append({"role": "user", "content": processed_query})

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
                reply_text = "No response was produced; task completion is unconfirmed."

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
                if "```" in reply_text:
                    console.print(f"[bold red]⚔️  KRATOS[/bold red] [dim]({runtime.model_name})[/dim] {approval_gate.mode_badge()}\n")
                    from kratos_agent.tui.highlighter import render_markdown_code_blocks
                    render_markdown_code_blocks(reply_text, console=console)
                else:
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
            except Exception as e:
                logger.debug("Failed clearing voice queue on exit: %s", e)
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
    except Exception as e:
        logger.debug("Failed rendering git status changes card: %s", e)

def main():
    args = [a.strip() for a in sys.argv[1:]]
    if any(a in ("--help", "-h", "/help", "help") for a in args):
        console.print(HELP_TEXT)
        return
    if any(a in ("--version", "-v", "version") for a in args):
        console.print("[bold red]Kratos Agent[/bold red] [bold gold1]v0.1.0[/bold gold1] - [dim]The Ghost of Sparta Codes[/dim]")
        return
    if any(a in ("--cli", "-c", "cli", "/cli") for a in args):
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
        reply = "No response was produced; task completion is unconfirmed."

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
