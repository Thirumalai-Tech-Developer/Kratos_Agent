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
import threading
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from ..core.agent_loop import format_tool_action_label
from ..core.d1_client import D1DatabaseClient, get_d1_client
from ..core.event_bus import event_bus
from ..core.memory import AgenticMemory
from ..core.runtime_contracts import RuntimeEvent

logger = logging.getLogger(__name__)

def get_web_dir() -> Path:
    """Resolve the directory containing static frontend build assets."""
    repo_root = Path(__file__).resolve().parents[3]
    frontend_dist = repo_root / "frontend" / "dist"
    if frontend_dist.is_dir() and (frontend_dist / "index.html").is_file():
        return frontend_dist
    return Path(__file__).resolve().parent

WEB_DIR = get_web_dir()


ALLOWED_ORIGINS = {
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:7860",
    "http://localhost:7860",
}


class KratosWebHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler for Kratos Web Console, Agent Arena & REST API."""

    server_version = "KratosViceCyberpunkServer/2.0"

    def log_message(self, format: str, *args: Any) -> None:
        if args and str(args[1]) not in ("200", "304"):
            logger.info("%s - %s", self.address_string(), format % args)

    def _send_cors_headers(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def do_OPTIONS(self) -> None:
        """Handle CORS pre-flight checks."""
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self) -> None:
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path

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
            elif path == "/api/live/status":
                self._handle_get_live_status()
                return

            # Static assets (Vite assets, images, fonts, HTML)
            current_web_dir = get_web_dir()
            rel_path = path.lstrip("/")
            if not rel_path or rel_path == "index.html":
                target_file = current_web_dir / "index.html"
                self._serve_file(target_file, "text/html; charset=utf-8")
                return

            target_file = (current_web_dir / rel_path).resolve()
            # Security check: ensure target is within current_web_dir
            try:
                target_file.relative_to(current_web_dir)
            except ValueError:
                self._send_json({"error": "Forbidden"}, status=HTTPStatus.FORBIDDEN)
                return

            if target_file.is_file():
                content_type, _ = mimetypes.guess_type(str(target_file))
                if not content_type:
                    if target_file.suffix.lower() == ".js":
                        content_type = "application/javascript; charset=utf-8"
                    elif target_file.suffix.lower() == ".css":
                        content_type = "text/css; charset=utf-8"
                    else:
                        content_type = "application/octet-stream"
                elif "text" in content_type or "javascript" in content_type:
                    content_type += "; charset=utf-8"
                self._serve_file(target_file, content_type)
                return

            # Fallback to index.html for SPA client-side routing
            index_file = current_web_dir / "index.html"
            if index_file.is_file():
                self._serve_file(index_file, "text/html; charset=utf-8")
                return

            # 404 Not Found
            self._send_json({"error": "Not Found"}, status=HTTPStatus.NOT_FOUND)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

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
        elif path == "/api/auth/agent-mode":
            self._handle_auth_agent_mode(payload)
            return
        elif path == "/api/live/control":
            self._handle_live_control(payload)
            return
        elif path == "/api/voice/stream":
            self._handle_voice_stream(payload)
            return
        elif path == "/api/voice/command":
            self._handle_voice_command(payload)
            return
        elif path == "/api/voice/panic":
            self._handle_voice_panic(payload)
            return
        elif path.startswith("/api/voice/task/") and path.endswith("/dispute"):
            task_id = path.split("/")[4]
            self._handle_voice_dispute(task_id, payload)
            return
        elif path == "/api/voice/task/dispute":
            self._handle_voice_dispute(payload.get("task_id", ""), payload)
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

    # ── Live Multimodal Handlers ───────────────────────────────────────────────

    def _handle_get_live_status(self) -> None:
        try:
            from kratos_agent.live import get_live_runtime
            live_rt = get_live_runtime()
            self._send_json(live_rt.get_status().to_dict())
        except Exception as e:
            self._send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_live_control(self, payload: dict[str, Any]) -> None:
        try:
            import asyncio

            from kratos_agent.live import get_live_runtime
            live_rt = get_live_runtime()
            action = str(payload.get("action", "")).lower().strip()
            val = payload.get("value")

            if action == "mute":
                live_rt.mute()
            elif action == "unmute":
                live_rt.unmute()
            elif action == "toggle_mute":
                if live_rt.get_status().muted:
                    live_rt.unmute()
                else:
                    live_rt.mute()
            elif action == "set_vision_mode" and isinstance(val, str):
                mode = val.lower().strip()
                if mode not in {"camera", "screen", "both", "none", "off"}:
                    self._send_json({"error": "Vision mode must be camera, screen, both, or off."}, status=HTTPStatus.BAD_REQUEST)
                    return
                if live_rt._loop and live_rt._loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(live_rt.set_vision_mode(mode), live_rt._loop)
                    future.result(timeout=15)
                else:
                    self._send_json({"error": "Live vision runtime is not running."}, status=HTTPStatus.SERVICE_UNAVAILABLE)
                    return
            elif action == "reconnect":
                live_rt.stop_background()
                live_rt.start_in_background()

            self._send_json(live_rt.get_status().to_dict())
        except Exception as e:
            self._send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_voice_dispute(self, task_id: str, payload: dict[str, Any]) -> None:
        try:
            import asyncio

            from kratos_agent.core.dispute import handle_dispute
            from kratos_agent.main import runtime
            obs = payload.get("user_observation", "") or payload.get("observation", "")
            lang = payload.get("lang", "auto")
            res = asyncio.run(handle_dispute(runtime, task_id=task_id, observation=obs, lang=lang))
            self._send_json(res.to_dict())
        except Exception as e:
            self._send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_voice_command(self, payload: dict[str, Any]) -> None:
        try:
            cmd = payload.get("command", "")
            from kratos_agent.main import run_agent
            res = run_agent(cmd)
            self._send_json({"ok": True, "result": res})
        except Exception as e:
            self._send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_voice_panic(self, payload: dict[str, Any]) -> None:
        try:
            from kratos_agent.ccs.safety_ops import panic_halt
            panic_halt(reason=payload.get("reason", "voice_panic"))
            self._send_json({"ok": True, "panic": "halted"})
        except Exception as e:
            self._send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_voice_stream(self, payload: dict[str, Any]) -> None:
        self._send_json({"ok": True, "stream": "active"})

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

    def _handle_chat_sse(self, payload: dict[str, Any]) -> None:
        """Streams real-time agent execution tokens, steps, and tool calls using SSE."""
        prompt = str(
            payload.get("prompt")
            or payload.get("message")
            or payload.get("query")
            or ""
        ).strip()
        if not prompt:
            self._send_json({"error": "Empty prompt"}, status=HTTPStatus.BAD_REQUEST)
            return

        if "agent_mode" in payload:
            agent_mode = bool(payload["agent_mode"])
        elif "is_agent_mode" in payload:
            agent_mode = bool(payload["is_agent_mode"])
        elif "mode" in payload:
            agent_mode = (payload["mode"] == "agent")
        else:
            agent_mode = True

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
        self._send_cors_headers()
        self.end_headers()

        def send_event(data: dict[str, Any]) -> None:
            try:
                line = f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
                self.wfile.write(line.encode("utf-8"))
                self.wfile.flush()
            except Exception as exc:
                logger.debug("Operation error suppressed: %s", exc)

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
            "step": {
                "tag": "INTENT ANALYSIS" if agent_mode else "NORMAL CHAT",
                "label": "Analyzing intent & reasoning..." if agent_mode else "Synthesizing response (Normal Chat Mode)..."
            },
            "label": "Analyzing intent & reasoning..." if agent_mode else "Synthesizing response (Normal Chat Mode)..."
        })

        # Event queue to bridge runtime event bus to HTTP client
        ev_queue: queue.Queue[dict[str, Any]] = queue.Queue()

        def on_runtime_event(ev: RuntimeEvent) -> None:
            kind = getattr(ev.kind, "value", str(ev.kind))
            p = ev.payload or {}

            if kind in ("understanding.started", "turn.started"):
                ev_queue.put({
                    "type": "step",
                    "step": {
                        "tag": "INSPECTING",
                        "label": "Classifying intent & inspecting context"
                    },
                    "label": "Classifying intent & inspecting context"
                })
            elif kind in ("planning.started", "plan.created"):
                title = p.get("goal") or "Formulating autonomous plan"
                ev_queue.put({
                    "type": "step",
                    "step": {
                        "tag": "PLANNING",
                        "label": title
                    },
                    "label": title
                })
            elif kind == "task.started":
                t_title = p.get("title") or "Executing planned task"
                ev_queue.put({
                    "type": "step",
                    "step": {
                        "tag": "TASK",
                        "label": f"Task: {t_title}"
                    },
                    "label": f"Task: {t_title}"
                })
            elif kind == "tool.started":
                tool_name = p.get("name") or "tool"
                tool_args = p.get("arguments") or {}
                action_lbl = format_tool_action_label(tool_name, tool_args)
                ev_queue.put({
                    "type": "tool_call",
                    "name": tool_name,
                    "label": f"[tool call] {action_lbl}",
                    "tool_call": {
                        "name": tool_name,
                        "label": action_lbl,
                        "args": tool_args
                    },
                    "args": tool_args
                })
                ev_queue.put({
                    "type": "step",
                    "step": {
                        "tag": "TOOL CALL",
                        "label": f"Calling: {action_lbl}"
                    },
                    "label": f"Calling: {action_lbl}"
                })
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
                ev_queue.put({
                    "type": "step",
                    "step": {
                        "tag": "VERIFICATION",
                        "label": "Running verification tests & validation"
                    },
                    "label": "Running verification tests & validation"
                })

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
            send_event({
                "type": "done",
                "result": f"Execution error: {exec_result['error']}",
                "reply": f"Execution error: {exec_result['error']}",
                "response": f"Execution error: {exec_result['error']}",
                "session_id": runtime.memory.active_session.session_id if runtime.memory.active_session else "default"
            })
        else:
            send_event({
                "type": "step",
                "step": {
                    "tag": "COMPLETE",
                    "label": "Turn completed successfully."
                },
                "label": "Turn completed successfully."
            })
            send_event({
                "type": "done",
                "result": exec_result["text"],
                "reply": exec_result["text"],
                "response": exec_result["text"],
                "content": exec_result["text"],
                "session_id": runtime.memory.active_session.session_id if runtime.memory.active_session else "default"
            })

    def _handle_voice_stream(self, payload: dict[str, Any]) -> None:
        """Omni Voice SSE Streaming Endpoint."""
        # Stub for Voice stream to be implemented according to Omni Spec
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "close")
        self._send_cors_headers()
        self.end_headers()
        
        # In a real implementation, this ties into event_adapter.py and the event_bus
        self.wfile.write(b"event: ready\ndata: {}\n\n")
        self.wfile.flush()

    def _handle_voice_command(self, payload: dict[str, Any]) -> None:
        """Omni Voice Command Execution."""
        # Stub for Voice command
        self._send_json({"status": "ok", "message": "Command received"})

    def _handle_voice_panic(self, payload: dict[str, Any]) -> None:
        """Omni Voice Panic trigger."""
        try:
            from kratos_agent.ccs.safety_ops import safety
            self._send_json({"status": "ok", "message": "PANIC TRIGGERED"})
            # safety.panic() halts the process, so send response first.
            threading.Thread(target=safety.panic, daemon=True).start()
        except Exception as e:
            self._send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_chat_sync(self, payload: dict[str, Any]) -> None:
        """Synchronous chat execution endpoint."""
        prompt = str(
            payload.get("prompt")
            or payload.get("message")
            or payload.get("query")
            or ""
        ).strip()
        if not prompt:
            self._send_json({"error": "Empty prompt"}, status=HTTPStatus.BAD_REQUEST)
            return

        if "agent_mode" in payload:
            agent_mode = bool(payload["agent_mode"])
        elif "is_agent_mode" in payload:
            agent_mode = bool(payload["is_agent_mode"])
        elif "mode" in payload:
            agent_mode = (payload["mode"] == "agent")
        else:
            agent_mode = True

        runtime = self.server.runtime
        from ..brain.config import get_normal_mode_model
        normal_model = get_normal_mode_model()
        active_model = runtime.model_name if agent_mode else normal_model
        try:
            result = runtime.run_agent(prompt, agent_mode=agent_mode)
            self._send_json({
                "result": result,
                "reply": result,
                "response": result,
                "session_id": runtime.memory.active_session.session_id if runtime.memory.active_session else "default",
                "model": active_model,
                "agent_mode": agent_mode
            })
        except Exception as e:
            self._send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_auth_agent_mode(self, payload: dict[str, Any]) -> None:
        """Verifies commander security clearance passcode to unlock Autonomous Agent Mode."""
        import os
        password = str(payload.get("password", "")).strip()
        expected = os.environ.get("AGENT_PASSWORD", "").strip()
        if expected and password == expected:
            self._send_json({"success": True, "message": "Security clearance granted"})
        else:
            self._send_json({"success": False, "error": "ACCESS DENIED // Invalid Passcode"}, status=HTTPStatus.UNAUTHORIZED)

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

    def _handle_create_session(self, payload: dict[str, Any]) -> None:
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

    def _handle_get_events(self, session_id: str | None = None) -> None:
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

    def _handle_sql_query(self, payload: dict[str, Any]) -> None:
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
                        except Exception as exc:
                            logger.debug("Operation error suppressed: %s", exc)
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
        self._send_cors_headers()
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
        runtime: Any | None = None,
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
    d1_db: D1DatabaseClient | None = None,
    memory: AgenticMemory | None = None,
    runtime: Any | None = None,
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

    # Start Gemini Live multimodal subsystem alongside Web (skip during automated test runs)
    if not os.getenv("PYTEST_CURRENT_TEST"):
        try:
            from kratos_agent.live import get_live_runtime
            live_runtime = get_live_runtime()
            live_runtime.start_in_background()
            print("🎤 Gemini Live Multimodal Subsystem: ONLINE\n")
        except Exception as e:
            print(f"⚠️ Gemini Live could not start: {e}\n")

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception as exc:
            logger.debug("Operation error suppressed: %s", exc)

    if daemon:
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        return server
    else:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down Kratos Web Server & Live subsystem...")
            try:
                from kratos_agent.live import get_live_runtime
                get_live_runtime().stop_background()
            except Exception as exc:
                logger.debug("Operation error suppressed: %s", exc)
            server.shutdown()
        return server


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Kratos Agent Vice Cyberpunk Console")
    parser.add_argument("--port", type=int, default=7860, help="Port to listen on (default: 7860)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")
    args = parser.parse_args()

    start_server(port=args.port, open_browser=not args.no_browser)
