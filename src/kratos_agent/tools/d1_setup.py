"""Cloudflare D1 Setup, Migration, and Verification CLI Tool.

Usage:
    python -m kratos_agent.tools.d1_setup
    python -m kratos_agent.tools.d1_setup --check
    python -m kratos_agent.tools.d1_setup --migrate
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from kratos_agent.core.d1_client import d1_db, DEFAULT_SCHEMA_PATH

console = Console(highlight=False)


def check_connection() -> bool:
    """Verifies D1 connectivity and displays detailed diagnostic table."""
    console.print("[bold red]⚔ KRATOS · CLOUDFLARE D1 DIAGNOSTICS[/bold red]\n")
    stats = d1_db.get_stats()

    table = Table(title="Cloudflare D1 Database Status", border_style="gold1")
    table.add_column("Property", style="bold cyan")
    table.add_column("Value", style="white")

    mode_label = "[bold green]Remote Cloudflare D1[/bold green]" if stats["is_remote"] else "[bold yellow]Local SQLite Mirror (.kratos/kratos_d1.db)[/bold yellow]"
    table.add_row("Operating Mode", mode_label)
    table.add_row("Database ID", stats["database_id"])
    table.add_row("Account ID", stats["account_id"])
    table.add_row("Health Status", "[bold green]ONLINE ✓[/bold green]" if stats["is_healthy"] else f"[bold red]ERROR: {stats['error']}[/bold red]")
    table.add_row("Query Latency", f"{stats['latency_ms']} ms")
    table.add_row("Sessions Stored", str(stats["sessions_count"]))
    table.add_row("Chat Turns Stored", str(stats["turns_count"]))
    table.add_row("Agentic Events Stored", str(stats["events_count"]))
    table.add_row("Commands Logged", str(stats["commands_count"]))

    console.print(table)
    console.print()

    if not stats["is_remote"]:
        console.print(
            Panel(
                "[bold yellow]Cloudflare credentials not detected in environment.[/bold yellow]\n\n"
                "Kratos is using the embedded zero-config SQLite mirror at:\n"
                f"[dim]{d1_db.local_db_path}[/dim]\n\n"
                "To connect to live Cloudflare D1, add these to your [bold green].env[/bold green]:\n"
                "[bold cyan]CLOUDFLARE_ACCOUNT_ID=\"your_account_id\"\n"
                "CLOUDFLARE_D1_DATABASE_ID=\"your_d1_database_id\"\n"
                "CLOUDFLARE_API_TOKEN=\"your_cloudflare_api_token\"[/bold cyan]\n\n"
                "See [bold gold1]docs/cloudflare_d1_setup.md[/bold gold1] for complete instructions.",
                title="[bold gold1]☁ Cloudflare D1 Connection Guide[/bold gold1]",
                border_style="yellow",
            )
        )
    else:
        console.print("[bold green]✓ Cloudflare D1 is configured and fully operational![/bold green]\n")

    return stats["is_healthy"]


def apply_schema() -> bool:
    """Applies d1_schema.sql to Cloudflare D1 and local SQLite mirror."""
    console.print("[dim]Applying schema from:[/dim] [cyan]" + str(DEFAULT_SCHEMA_PATH) + "[/cyan]")
    try:
        ok = d1_db.init_schema()
        if ok:
            console.print("[bold green]✓ Schema initialized successfully on D1 database.[/bold green]\n")
            return True
        console.print("[bold red]✗ Failed to load schema file.[/bold red]\n")
        return False
    except Exception as exc:
        console.print(f"[bold red]✗ Schema error:[/bold red] {exc}\n")
        return False


def migrate_local_sessions() -> int:
    """Migrates historical .kratos/sessions JSON and events.jsonl files into D1."""
    sessions_dir = Path.cwd() / ".kratos" / "sessions"
    if not sessions_dir.exists():
        console.print("[yellow]No local .kratos/sessions directory found to migrate.[/yellow]\n")
        return 0

    count = 0
    console.print(f"[dim]Scanning {sessions_dir} for legacy sessions...[/dim]")

    for f in sessions_dir.glob("session_*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            sid = data.get("session_id", f.stem)
            title = data.get("title", sid)
            model = data.get("model", "antigravity/gemini-3.7-flash-high")
            created_at = data.get("created_at", "")
            updated_at = data.get("updated_at", created_at)
            status = data.get("last_status", "idle")

            # 1. Insert Session
            d1_db.execute(
                """INSERT OR REPLACE INTO sessions 
                   (id, title, model, created_at, updated_at, last_status, plan_json, files_changed_json, verification_status_json, notes_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    sid,
                    title,
                    model,
                    created_at,
                    updated_at,
                    status,
                    json.dumps(data.get("plan") or {}),
                    json.dumps(data.get("files_changed") or {}),
                    json.dumps(data.get("verification_status") or {}),
                    json.dumps(data.get("notes") or {}),
                ],
            )

            # 2. Insert Turns
            turns = data.get("turns", [])
            for idx, turn in enumerate(turns):
                tid = turn.get("id") or f"turn_{sid}_{idx}"
                d1_db.execute(
                    """INSERT OR REPLACE INTO turns (id, session_id, turn_index, timestamp, user_query, agent_reply, tools_used_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    [
                        tid,
                        sid,
                        idx,
                        turn.get("timestamp", ""),
                        turn.get("user", ""),
                        turn.get("agent", ""),
                        json.dumps(turn.get("tools_used") or []),
                    ],
                )

            # 3. Insert Commands
            cmds = data.get("executed_commands", [])
            for idx, cmd in enumerate(cmds):
                cid = cmd.get("id") or f"cmd_{sid}_{idx}"
                d1_db.execute(
                    """INSERT OR REPLACE INTO commands (id, session_id, timestamp, command, returncode, output_preview)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    [
                        cid,
                        sid,
                        cmd.get("timestamp", ""),
                        cmd.get("command", ""),
                        cmd.get("returncode", 0),
                        cmd.get("output_preview", ""),
                    ],
                )

            # 4. Insert Events if events.jsonl exists
            events_file = sessions_dir / sid / "events.jsonl"
            if events_file.exists():
                for line in events_file.read_text(encoding="utf-8").splitlines():
                    try:
                        ev = json.loads(line)
                        eid = ev.get("id") or f"evt_{sid}_{len(line)}"
                        kind = ev.get("kind", "unknown")
                        ts = float(ev.get("timestamp", 0))
                        payload = json.dumps(ev.get("payload") or {})
                        turn_id = ev.get("turn_id", "")
                        d1_db.execute(
                            """INSERT OR REPLACE INTO agentic_events (id, session_id, turn_id, kind, timestamp, payload_json)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            [eid, sid, turn_id, kind, ts, payload],
                        )
                    except Exception:
                        continue

            count += 1
            console.print(f"  [bold green]✓ Migrated:[/bold green] {title} ({sid})")
        except Exception as exc:
            console.print(f"  [bold red]✗ Failed to migrate {f.name}:[/bold red] {exc}")

    console.print(f"\n[bold green]Migration complete! Migrated {count} session(s) into D1.[/bold green]\n")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Kratos Cloudflare D1 Setup & Diagnostics")
    parser.add_argument("--check", action="store_true", help="Check Cloudflare D1 connection and statistics")
    parser.add_argument("--schema", action="store_true", help="Apply SQL schema to D1 database")
    parser.add_argument("--migrate", action="store_true", help="Migrate existing local sessions to D1")
    args = parser.parse_args()

    if args.check:
        check_connection()
    elif args.schema:
        apply_schema()
    elif args.migrate:
        apply_schema()
        migrate_local_sessions()
    else:
        # Default: check, apply schema, and show status
        apply_schema()
        check_connection()
        migrate_local_sessions()


if __name__ == "__main__":
    main()
