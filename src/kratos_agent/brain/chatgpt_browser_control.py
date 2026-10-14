"""Authenticated local companion for the regular-browser extension's login panel."""

from __future__ import annotations

import argparse
import hmac
import json
import logging
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests

from .account_store import AccountStore
from .chatgpt_web import ChatGPTWebAccounts, chatgpt_web_accounts
from .config import BrainError
from .web_providers import WEB_PROVIDERS

logger = logging.getLogger(__name__)


class BrowserControlMonitor:
    """Keep the shared extension panel available while a workspace is running."""

    def __init__(self, manager=chatgpt_web_accounts, *, source=None, interval=10):
        self.manager, self.source, self.interval = manager, source, interval
        self.stopped = threading.Event()
        self.thread = None

    def check(self):
        try:
            # A fresh installation must not generate credentials or install files
            # simply by starting Studio. Once connected, reuse the user's setup.
            if not (self.manager.store.root / "browser-extension/config.js").is_file():
                state = self.manager.store.read()
                if not state.get('web_accounts'):
                    return
            ensure_browser_control(self.manager, source=self.source)
            self.manager.retry_gateway_sync()
        except (BrainError, OSError, RuntimeError):
            logger.warning("Browser connection panel unavailable; recovery will retry")

    def start(self):
        def monitor():
            while not self.stopped.is_set():
                self.check()
                self.stopped.wait(self.interval)

        self.thread = threading.Thread(target=monitor, name="kratos-browser-panel", daemon=True)
        self.thread.start()
        return self

    def close(self):
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=4)


class BrowserPanel:
    def __init__(self, manager, source=None):
        self.manager = manager
        self.source = source
        self.lock = threading.Lock()
        self.busy = False
        self.operation = ""
        self.error = ""
        self.error_account = ""
        self.message = ""

    def status(self):
        state = self.manager.store.read()
        accounts = []
        for key, record in state.get("web_accounts", {}).items():
            connected = bool(record.get("storage_state")) and not record.get("session_expired", False)
            accounts.append(
                {
                    "id": key,
                    "provider": record.get("provider_id", "chatgpt-web"),
                    "provider_name": WEB_PROVIDERS.get(record.get("provider_id", "chatgpt-web"), {}).get("name", "Browser"),
                    "email": record.get("email", ""),
                    "connected": connected,
                    "session_expired": bool(record.get("session_expired")),
                    "cookie_store_id": record.get("cookie_store_id"),
                    "auto_refresh": bool(record.get("storage_state")) and isinstance(record.get("cookie_store_id"), str),
                    "cookies_checked_at": record.get("cookies_checked_at"),
                    "active": connected
                    and state.get("provider") in {"chatgpt-web", "browser-web"}
                    and state.get("active_web_account") == key,
                    "model": record.get("model", ""),
                    "reasoning_effort": record.get("reasoning_effort"),
                    "gateway_sync": {
                        name: record.get("gateway_sync", {"synced": False, "pending": True})[name]
                        for name in ("synced", "pending", "action", "provider", "usage", "enabled", "connection_id", "checked_at", "error")
                        if name in record.get("gateway_sync", {"synced": False, "pending": True})
                    },
                    "models": [
                        {"id": m["id"], "display_name": m.get("display_name", m["id"]), "effort_tiers": m.get("effort_tiers", []), "supports_reasoning": m.get("supports_reasoning", False)}
                        for m in record.get("models", [])
                    ],
                }
            )
        with self.lock:
            for account in accounts:
                account["error"] = (
                    self.error if self.error_account == account["id"] else ""
                )
            return {
                "ready": True,
                "providers": [{"id": key, "name": value["name"]} for key, value in WEB_PROVIDERS.items()],
                "accounts": accounts,
                "busy": self.busy,
                "operation": self.operation,
                "error": self.error,
                "message": self.message,
            }

    def start(self, action, data):
        if action not in {"connect", "select", "disconnect", "models", "sync_service"}:
            raise ValueError("Unknown connection action")
        if action != "connect" and not isinstance(data.get("account_id"), str):
            raise ValueError("Choose a saved account")
        if action == "select" and not isinstance(data.get("model"), str):
            raise ValueError("Choose an available model")
        if action == "connect" and data.get("provider", "chatgpt-web") not in WEB_PROVIDERS:
            raise ValueError("Choose a supported browser provider")
        if data.get("reasoning_effort") is not None and data["reasoning_effort"] not in {"low", "medium", "high", "xhigh", "max", "minimal", "none"}:
            raise ValueError("Choose a supported thinking level")
        with self.lock:
            if self.busy:
                raise RuntimeError("A connection operation is already running")
            self.busy, self.operation, self.error, self.message = True, action, "", ""
            self.error_account = ""
        threading.Thread(target=self._run, args=(action, data), daemon=True).start()

    def _run(self, action, data):
        error, message = "", ""
        try:
            if action == "connect":
                options = {"source": self.source}
                if data.get("snapshot") is not None:
                    options["snapshot"] = data["snapshot"]
                if data.get("provider", "chatgpt-web") != "chatgpt-web":
                    options["provider"] = data["provider"]
                result = self.manager.login(**options)
                message = "Connected. Choose a model to use it in Kratos."
                if not result.get("models"):
                    message = "Connected. This executor has no matching models for this account."
            elif action == "select":
                options = {}
                if data.get("reasoning_effort") is not None:
                    options["effort"] = data["reasoning_effort"]
                self.manager.select(data["account_id"], data["model"], **options)
                message = "Model selected. In Kratos, refresh Choose a model to apply this connection."
            elif action == "disconnect":
                self.manager.sign_out(data["account_id"])
                message = "Disconnected from Kratos. Your browser remains signed in."
            elif action == "sync_service":
                synced = self.manager.sync_gateway_account(data["account_id"])
                if not synced.get("synced"):
                    error = synced.get("error", "OmniRoute cookie sync is unavailable.")
                else:
                    message = "Cookies saved by OmniRoute. ChatGPT service access is native Codex only." if synced.get("usage") == "native_codex_only" else "Cookies saved by the local OmniRoute service."
            else:
                self.manager.models(data["account_id"])
                message = "Website connection and model list checked."
        except BrainError as exc:
            # BrainError messages are deliberately credential-free at the bridge boundary.
            error = str(exc)
        except Exception:  # noqa: BLE001 -- Never expose raw worker exceptions or credentials in the popup.
            error = "Connection failed. Check the selected website tab and try again."
        finally:
            with self.lock:
                self.busy, self.error, self.message = False, error, message
                self.error_account = data.get("account_id", "") if error else ""


def create_server(panel, token, *, port=20131):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Authentication headers and account data never enter HTTP logs.

        def respond(self, code, body):
            encoded = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def authorized(self):
            if not hmac.compare_digest(
                self.headers.get("Authorization", "").encode(),
                ("Bearer " + token).encode(),
            ):
                self.respond(401, {"error": "Unauthorized connection"})
                return False
            return True

        def do_GET(self):
            if not self.authorized():
                return
            if self.path != "/status":
                self.respond(404, {"error": "Unknown connection endpoint"})
                return
            try:
                self.respond(200, panel.status())
            except (OSError, RuntimeError, ValueError, KeyError, TypeError):
                self.respond(500, {"error": "Protected account storage is unavailable"})

        def do_POST(self):
            if not self.authorized():
                return
            if self.path not in {"/connect", "/select", "/disconnect", "/models", "/sync", "/sync_service"}:
                self.respond(404, {"error": "Unknown connection endpoint"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= (12 * 1024 * 1024 if self.path in {"/connect", "/sync"} else 4096):
                    raise TypeError("Invalid connection request")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise TypeError("Invalid connection request")
                if self.path == "/sync":
                    self.respond(200, panel.manager.sync_snapshot(data.get("provider"), data.get("snapshot")))
                    return
                panel.start(self.path[1:], data)
                self.respond(202, {"accepted": True})
            except (ValueError, TypeError):
                self.respond(400, {"error": "Choose a valid account and model"})
            except BrainError:
                self.respond(400, {"error": "The collected cookie snapshot is invalid or expired"})
            except RuntimeError:
                self.respond(
                    409, {"error": "A connection operation is already running"}
                )

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def ensure_browser_control(manager=chatgpt_web_accounts, *, source=None):
    """Start one hidden companion, reusing a verified receiver when already running."""
    setup = manager.prepare_browser()
    control_url = f"http://127.0.0.1:{setup['control_port']}"
    session = requests.Session()
    session.trust_env = False  # User proxies must never receive the local bearer token.
    headers = {"Authorization": "Bearer " + setup["token"]}

    def running():
        try:
            response = session.get(
                control_url + "/status", headers=headers, timeout=0.5
            )
            if response.status_code == 401:
                raise BrainError("Another application owns the browser connection port")
            return response.ok and response.json().get("ready") is True
        except (requests.RequestException, ValueError):
            return False

    try:
        if running():
            return {"running": True}
        resolved = manager.source(source)
        flags = (
            (subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
            if os.name == "nt"
            else 0
        )
        with manager.session_lock("browser-panel-start", 10):
            if running():
                return {"running": True}
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "kratos_agent.brain.chatgpt_browser_control",
                    "--source",
                    str(resolved),
                    "--account-dir",
                    str(manager.store.root),
                ],
                cwd=resolved,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
                start_new_session=os.name != "nt",
            )
            for _ in range(30):
                if running():
                    return {"running": True}
                if process.poll() is not None:
                    break
                time.sleep(0.1)
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
        raise BrainError(
            "Could not start the browser connection panel; run kratos-connect browser"
        )
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(
        description="Regular-browser login panel companion"
    )
    parser.add_argument("--source")
    parser.add_argument("--account-dir", type=Path)
    args = parser.parse_args()
    manager = ChatGPTWebAccounts(AccountStore(args.account_dir))
    setup = manager.prepare_browser()
    server = create_server(
        BrowserPanel(manager, args.source), setup["token"], port=setup["control_port"]
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
