"""
Kratos Web Server
Lightweight HTTP server serving the Cyberpunk + GTA 6 Recruiter Console, Live Agent Arena, and Cloudflare D1 dashboard.
Uses Python's standard library http.server for zero external dependencies.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import queue
import sys
import threading
import time
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.d1_client import get_d1_client, D1DatabaseClient
from ..core.memory import AgenticMemory
from ..core.event_bus import event_bus
from ..core.agent_loop import format_tool_action_label
from ..core.runtime_contracts import EventKind, RuntimeEvent

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent


class KratosWebHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler for Kratos Web Console, Agent Arena & REST API."""

    server_version = "KratosViceCyberpunkServer/2.0"

    def log_message(self, format: str, *args: Any) -> None:
        if args and str(args[1]) not in ("200", "304"):
            logger.info("%s - %s", self.address_string(), format % args)

    def do_OPTIONS(self) -> None:
        """Handle CORS pre-flight checks."""
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # Static assets
        if path in ("/", "/index.html"):
            self._serve_file(WEB_DIR / "index.html", "text/html; charset=utf-8")
            return
        elif path == "/app.css":
            self._serve_file(WEB_DIR / "app.css", "text/css; charset=utf-8")
            return
        elif path == "/app.js":
            self._serve_file(WEB_DIR / "app.js", "application/javascript; charset=utf-8")
            return
        elif path == "/highlighter.js":
            self._serve_file(WEB_DIR / "highlighter.js", "application/javascript; charset=utf-8")
            return
        elif path.startswith("/fonts/"):
            font_filename = Path(path).name
            font_path = WEB_DIR / "fonts" / font_filename
            content_type = "font/ttf" if font_path.suffix.lower() == ".ttf" else "font/otf"
            self._serve_file(font_path, content_type)
            return

        # REST API Routes
        if path == "/api/stats":
            self._handle_get_stats()
            return
        elif path == "/api/telemetry":
            self._handle_get_telemetry()
            return
        elif path == "/api/tools":
            self._handle_get_tools()
            return
        elif path == "/api/sessions":
            self._handle_get_sessions()
            return
        elif path.startswith("/api/sessions/"):
            session_id = path.replace("/api/sessions/", "").strip("/")
            self._handle_get_session_detail(session_id)
            return
        elif path.startswith("/api/events/"):
            session_id = path.replace("/api/events/", "").strip("/")
            self._handle_get_events(session_id)
            return
        elif path == "/api/events":
            self._handle_get_events()
            return

        # 404 Not Found
        self._send_json({"error": "Not Found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"

        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            payload = {}

        if path == "/api/chat":
            self._handle_chat_sse(payload)
            return
        elif path == "/api/chat/sync":
            self._handle_chat_sync(payload)
            return
        elif path == "/api/sessions":
            self._handle_create_session(payload)
            return
        elif path == "/api/query":
            self._handle_sql_query(payload)
            return

        self._send_json({"error": "Not Found"}, status=HTTPStatus.NOT_FOUND)

    def do_DELETE(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/sessions/"):
            session_id = path.replace("/api/sessions/", "").strip("/")
            self._handle_delete_session(session_id)
            return

        self._send_json({"error": "Not Found"}, status=HTTPStatus.NOT_FOUND)

    # ── Static File Helper ─────────────────────────────────────────────────────

    def _serve_file(self, file_path: Path, content_type: str) -> None:
        if not file_path.is_file():
            self._send_json({"error": "File Not Found"}, status=HTTPStatus.NOT_FOUND)
            return
        try:
            content = file_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache, must-revalidate")
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self._send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    # ── Live Agent Streaming (Server-Sent Events) ──────────────────────────────

    def _handle_chat_sse(self, payload: Dict[str, Any]) -> None:
        """Streams real-time agent execution tokens, steps, and tool calls using SSE."""
        prompt = str(payload.get("prompt", "")).strip()
        if not prompt:
            self._send_json({"error": "Empty prompt"}, status=HTTPStatus.BAD_REQUEST)
            return

        agent_mode = bool(payload.get("agent_mode", True))
        runtime = self.server.runtime
        requested_session_id = payload.get("session_id")
        if requested_session_id and runtime.memory:
            runtime.memory.load_session(requested_session_id)
            runtime.activate_session()

        # Send SSE Headers
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        def send_event(data: Dict[str, Any]) -> None:
            try:
                line = f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
                self.wfile.write(line.encode("utf-8"))
                self.wfile.flush()
            except Exception:
                pass

        from ..brain.config import get_normal_mode_model
        normal_model = get_normal_mode_model()
        active_model = runtime.model_name if agent_mode else normal_model

        # Send initial turn start
        send_event({
            "type": "start",
            "prompt": prompt,
            "session_id": runtime.memory.active_session.session_id if runtime.memory.active_session else "default",
            "model": active_model,
            "agent_mode": agent_mode
        })
        send_event({
            "type": "step",
            "step": "reasoning",
            "label": "Analyzing intent & reasoning..." if agent_mode else "Highly Restricted Agent Mode / Normal Chat Mode (Static Web Hosting)"
        })

        # Event queue to bridge runtime event bus to HTTP client
        ev_queue: queue.Queue[Dict[str, Any]] = queue.Queue()

        def on_runtime_event(ev: RuntimeEvent) -> None:
            kind = getattr(ev.kind, "value", str(ev.kind))
            p = ev.payload or {}

            if kind in ("understanding.started", "turn.started"):
                ev_queue.put({"type": "step", "step": "reasoning", "label": "Classifying intent & inspecting context"})
            elif kind in ("planning.started", "plan.created"):
                title = p.get("goal") or "Formulating autonomous plan"
                ev_queue.put({"type": "step", "step": "planning", "label": title})
            elif kind == "task.started":
                t_title = p.get("title") or "Executing planned task"
                ev_queue.put({"type": "step", "step": "planning", "label": f"Task: {t_title}"})
            elif kind == "tool.started":
                tool_name = p.get("name") or "tool"
                tool_args = p.get("arguments") or {}
                action_lbl = format_tool_action_label(tool_name, tool_args)
                ev_queue.put({
                    "type": "tool_call",
                    "name": tool_name,
                    "label": f"[tool call] {action_lbl}",
                    "args": tool_args
                })
                ev_queue.put({"type": "step", "step": "tool_call", "label": f"Calling: {action_lbl}"})
            elif kind == "tool.completed":
                tool_name = p.get("name") or "tool"
                content = p.get("content") or ""
                ev_queue.put({
                    "type": "tool_result",
                    "name": tool_name,
                    "result": content[:300] + ("..." if len(content) > 300 else "")
                })
            elif kind == "model.chunk":
                token = p.get("chunk") or ""
                if token:
                    ev_queue.put({"type": "token", "token": token})
            elif kind == "verification.started":
                ev_queue.put({"type": "step", "step": "verifying", "label": "Running verification tests & validation"})

        event_bus.subscribe(on_runtime_event)

        # Worker thread to execute agent runtime turn
        exec_result = {"text": "", "error": None}

        def run_worker():
            try:
                exec_result["text"] = runtime.run_agent(prompt, agent_mode=agent_mode)
            except Exception as ex:
                exec_result["error"] = str(ex)
            finally:
                ev_queue.put({"type": "__COMPLETED__"})

        worker_thread = threading.Thread(target=run_worker, daemon=True)
        worker_thread.start()

        # Stream queued events to browser
        while True:
            try:
                item = ev_queue.get(timeout=0.2)
                if item.get("type") == "__COMPLETED__":
                    break
                send_event(item)
            except queue.Empty:
                if not worker_thread.is_alive():
                    break
                # Keep-alive ping
                try:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                except Exception:
                    break

        event_bus.unsubscribe(on_runtime_event)

        # Final response event
        if exec_result["error"]:
            send_event({"type": "error", "message": exec_result["error"]})
        else:
            send_event({
                "type": "done",
                "result": exec_result["text"],
                "session_id": runtime.memory.active_session.session_id if runtime.memory.active_session else "default"
            })

    def _handle_chat_sync(self, payload: Dict[str, Any]) -> None:
        """Synchronous chat execution endpoint."""
        prompt = str(payload.get("prompt", "")).strip()
        if not prompt:
            self._send_json({"error": "Empty prompt"}, status=HTTPStatus.BAD_REQUEST)
            return

        agent_mode = bool(payload.get("agent_mode", True))
        runtime = self.server.runtime
        from ..brain.config import get_normal_mode_model
        normal_model = get_normal_mode_model()
        active_model = runtime.model_name if agent_mode else normal_model
        try:
            result = runtime.run_agent(prompt, agent_mode=agent_mode)
            self._send_json({
                "result": result,
                "session_id": runtime.memory.active_session.session_id if runtime.memory.active_session else "default",
                "model": active_model,
                "agent_mode": agent_mode
            })
        except Exception as e:
            self._send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    # ── REST API Handlers ──────────────────────────────────────────────────────

    def _handle_get_stats(self) -> None:
        d1: D1DatabaseClient = self.server.d1_db
        stats = d1.get_stats()
        self._send_json(stats)

    def _handle_get_telemetry(self) -> None:
        runtime = self.server.runtime
        d1: D1DatabaseClient = self.server.d1_db
        stats = d1.get_stats()
        active_sess = runtime.memory.active_session if runtime.memory else None
        from ..brain.config import get_normal_mode_model

        self._send_json({
            "model": runtime.model_name,
            "normal_mode_model": get_normal_mode_model(),
            "workspace": str(runtime.workspace),
            "tools_count": len(runtime.tools),
            "active_session": {
                "id": active_sess.session_id if active_sess else None,
                "title": active_sess.title if active_sess else "None",
                "turns_count": len(active_sess.turns) if active_sess else 0,
            } if active_sess else None,
            "d1_database_id": stats.get("database_id"),
            "d1_mode": stats.get("mode"),
            "is_remote_d1": stats.get("is_remote", False),
            "latency_ms": stats.get("latency_ms", 0),
        })

    def _handle_get_tools(self) -> None:
        runtime = self.server.runtime
        tools_list = []
        for t in runtime.tools:
            tools_list.append({
                "name": t.name,
                "description": t.description or "Autonomous utility tool",
                "permission": getattr(t.permission, "value", str(t.permission)),
                "timeout_seconds": getattr(t, "timeout_seconds", 300),
            })
        self._send_json(tools_list)

    def _handle_get_sessions(self) -> None:
        memory: AgenticMemory = self.server.memory
        sessions = memory.list_sessions()
        self._send_json(sessions)

    def _handle_get_session_detail(self, session_id: str) -> None:
        memory: AgenticMemory = self.server.memory
        if not memory.load_session(session_id):
            self._send_json({"error": f"Session {session_id} not found"}, status=HTTPStatus.NOT_FOUND)
            return

        session = memory.active_session
        if not session:
            self._send_json({"error": "Active session is None"}, status=HTTPStatus.NOT_FOUND)
            return

        self._send_json({
            "id": session.session_id,
            "session_id": session.session_id,
            "title": session.title,
            "model": session.model,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "turns": session.turns,
            "plan": session.plan,
            "last_status": session.last_status,
            "files_changed": getattr(session, "files_changed", {}),
            "executed_commands": getattr(session, "executed_commands", []),
        })

    def _handle_create_session(self, payload: Dict[str, Any]) -> None:
        memory: AgenticMemory = self.server.memory
        title = payload.get("title", "Web Console Session")
        model = payload.get("model", "auto")
        session = memory.create_session(title=title, model=model)
        self._send_json({
            "id": session.session_id,
            "session_id": session.session_id,
            "title": session.title,
            "model": session.model,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "turns_count": 0,
        }, status=HTTPStatus.CREATED)

    def _handle_delete_session(self, session_id: str) -> None:
        memory: AgenticMemory = self.server.memory
        success = memory.delete_session(session_id)
        if success:
            self._send_json({"success": True, "id": session_id})
        else:
            self._send_json({"error": f"Failed to delete session {session_id}"}, status=HTTPStatus.NOT_FOUND)

    def _handle_get_events(self, session_id: Optional[str] = None) -> None:
        d1: D1DatabaseClient = self.server.d1_db
        if session_id:
            query = "SELECT * FROM agentic_events WHERE session_id = ? ORDER BY timestamp ASC"
            params = [session_id]
        else:
            query = "SELECT * FROM agentic_events ORDER BY timestamp DESC LIMIT 150"
            params = []

        try:
            res = d1.execute(query, params)
            events = []
            for row in res:
                ev = dict(row)
                raw_p = ev.get("payload_json") or ev.get("payload")
                if isinstance(raw_p, str):
                    try:
                        ev["payload"] = json.loads(raw_p)
                    except Exception:
                        ev["payload"] = {"raw": raw_p}
                else:
                    ev["payload"] = raw_p or {}
                events.append(ev)
            self._send_json(events)
        except Exception as e:
            self._send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_sql_query(self, payload: Dict[str, Any]) -> None:
        sql = payload.get("sql", "").strip()
        if not sql:
            self._send_json({"error": "Empty SQL query"}, status=HTTPStatus.BAD_REQUEST)
            return

        d1: D1DatabaseClient = self.server.d1_db
        try:
            res = d1.execute(sql)
            rows = []
            for r in res:
                row_dict = dict(r)
                for k, v in row_dict.items():
                    if isinstance(v, str) and (v.startswith("{") or v.startswith("[")):
                        try:
                            row_dict[k] = json.loads(v)
                        except Exception:
                            pass
                rows.append(row_dict)

            source = "cloudflare_d1" if d1.is_remote else "sqlite_mirror"
            self._send_json({"rows": rows, "count": len(rows), "source": source})
        except Exception as e:
            self._send_json({"error": str(e)}, status=HTTPStatus.BAD_REQUEST)

    def _send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        content = json.dumps(data, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(content)


class KratosServer(ThreadingHTTPServer):
    """Custom server instance holding references to D1, Memory, and Runtime."""

    def __init__(
        self,
        server_address,
        RequestHandlerClass,
        d1_db: D1DatabaseClient,
        memory: AgenticMemory,
        runtime: Optional[Any] = None,
    ):
        self.d1_db = d1_db
        self.memory = memory
        if runtime is None:
            from ..main import runtime as default_runtime
            self.runtime = default_runtime
        else:
            self.runtime = runtime
        super().__init__(server_address, RequestHandlerClass)


def start_server(
    port: int = 7860,
    open_browser: bool = True,
    d1_db: Optional[D1DatabaseClient] = None,
    memory: Optional[AgenticMemory] = None,
    runtime: Optional[Any] = None,
    daemon: bool = False,
) -> KratosServer:
    """Start the Kratos Vice Cyberpunk Web Server."""
    if d1_db is None:
        d1_db = get_d1_client()
        d1_db.init_schema()

    if memory is None:
        memory = AgenticMemory(d1_db=d1_db)

    server = None
    for attempt_port in range(port, port + 10):
        try:
            server = KratosServer(
                ("127.0.0.1", attempt_port),
                KratosWebHandler,
                d1_db=d1_db,
                memory=memory,
                runtime=runtime,
            )
            port = attempt_port
            break
        except OSError:
            continue

    if not server:
        raise RuntimeError(f"Could not bind Kratos Web Server to port {port} or next 10 ports.")

    url = f"http://127.0.0.1:{port}"
    print(f"\n🌴⚔️  KRATOS VI: VICE CYBERPUNK CONSOLE active at: {url}")
    print(f"📊 Storage: {'Cloudflare D1 (Cloud)' if d1_db.is_remote else 'D1 SQLite Mirror (Local)'}")
    print("⚡ Real-time Agent Arena & Tool Dispatcher ready.\n")

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    if daemon:
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        return server
    else:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down Kratos Web Server...")
            server.shutdown()
        return server


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Kratos Agent Vice Cyberpunk Console")
    parser.add_argument("--port", type=int, default=7860, help="Port to listen on (default: 7860)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")
    args = parser.parse_args()

    start_server(port=args.port, open_browser=not args.no_browser)
