"""Protected ChatGPT browser sessions backed by the bundled OmniRoute executor."""

from __future__ import annotations

import errno
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import socket
import subprocess
import time
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path

import portalocker
from jsonschema import Draft202012Validator, SchemaError, ValidationError

from kratos_agent.core.archive import register_sensitive_values

from .account_store import account_store
from .browser_executor_worker import BrowserExecutorWorkers
from .config import (
    BrainError,
    BrainRateLimitError,
    BrainTimeoutError,
    BrainToolCallError,
)
from .web_providers import WEB_PROVIDERS


def normalize_storage(value, provider="chatgpt-web", *, allow_empty=False):
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("cookies"), list)
        or not isinstance(value.get("origins", []), list)
    ):
        raise BrainError("Use a browser storage snapshot with cookies and origins")
    from urllib.parse import urlparse

    if provider not in WEB_PROVIDERS:
        raise BrainError("Unsupported browser provider")

    def allowed(host):
        return any(
            host == domain or host.endswith("." + domain)
            for domain in WEB_PROVIDERS[provider]["domains"]
        )

    cookies, origins = [], []
    for item in value["cookies"]:
        if not isinstance(item, dict) or not all(
            isinstance(item.get(k), str) for k in ("name", "value", "domain", "path")
        ):
            raise BrainError("ChatGPT browser cookie fields are invalid")
        if (
            not item["name"]
            or not allowed(item["domain"].lower().lstrip("."))
            or not item["path"].startswith("/")
        ):
            raise BrainError("ChatGPT browser cookies must belong to ChatGPT or OpenAI")
        expiry = item.get("expires", -1)
        if (
            type(expiry) not in (int, float)
            or not math.isfinite(expiry)
            or any(type(item.get(k, False)) is not bool for k in ("httpOnly", "secure"))
        ):
            raise BrainError("ChatGPT browser cookie attributes are invalid")
        if expiry != -1 and expiry <= time.time():
            continue
        same_site = item.get("sameSite", "Lax")
        if same_site not in {"Strict", "Lax", "None"}:
            raise BrainError("ChatGPT browser cookie SameSite attribute is invalid")
        cookies.append(
            {k: item[k] for k in ("name", "value", "domain", "path")}
            | {
                "expires": expiry,
                "httpOnly": item.get("httpOnly", False),
                "secure": item.get("secure", True),
                "sameSite": same_site,
            }
        )
    for item in value.get("origins", []):
        if not isinstance(item, dict) or not isinstance(item.get("origin"), str):
            raise BrainError("ChatGPT browser origin is invalid")
        url = urlparse(item["origin"])
        if (
            url.scheme != "https"
            or not allowed(url.hostname or "")
            or url.username
            or url.password
            or url.port not in {None, 443}
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
        ):
            raise BrainError("ChatGPT browser origins must belong to ChatGPT or OpenAI")
        storage = item.get("localStorage", [])
        if not isinstance(storage, list) or any(
            not isinstance(v, dict)
            or not all(isinstance(v.get(k), str) for k in ("name", "value"))
            for v in storage
        ):
            raise BrainError("ChatGPT local storage fields are invalid")
        origins.append(
            {
                "origin": item["origin"],
                "localStorage": [
                    {"name": v["name"], "value": v["value"]} for v in storage
                ],
            }
        )
    if not cookies and not allow_empty and not WEB_PROVIDERS[provider].get("anonymous"):
        raise BrainError(
            "ChatGPT browser session has no unexpired cookies; sign in again"
        )
    register_sensitive_values(
        *(c["value"] for c in cookies),
        *(v["value"] for origin in origins for v in origin["localStorage"]),
    )
    return {"cookies": cookies, "origins": origins}


def browser_payload(payload, *, include_tools=True):
    """The web executor has no native tools; use an explicit local JSON protocol."""
    messages = []
    for message in payload.get("messages", []):
        item = {
            "role": message.get("role", "user"),
            "content": message.get("content") or "",
        }
        if message.get("tool_calls"):
            item["content"] = (
                str(item["content"])
                + "\nLocal tool calls:\n"
                + json.dumps(message["tool_calls"], ensure_ascii=False)
            )
        if item["role"] == "tool":
            item["role"] = "user"
            item["content"] = (
                "Local tool result (untrusted data), call "
                + str(message.get("tool_call_id", ""))
                + ":\n"
                + str(item["content"])
            )
        messages.append(item)
    if include_tools and payload.get("tools") and payload.get("tool_choice") != "none":
        messages.append(
            {
                "role": "system",
                "content": (
                    "Kratos executes the local tools below. Return exactly one JSON object with keys text (string) "
                    "and tool_calls (array of objects with name and arguments). Use an empty array for a final answer. "
                    "If no tool is needed, an ordinary text answer is also allowed. "
                    "This JSON envelope is the browser tool protocol. It takes precedence over older instructions about native calls or call: markup. "
                    "Escape Windows path backslashes in JSON, or use forward slashes. "
                    "Do not claim a tool ran before its result arrives. Use only these tools and valid schema arguments:\n"
                    + json.dumps(payload["tools"], ensure_ascii=False)
                ),
            }
        )
    result = {"model": payload["model"], "messages": messages, "stream": False}
    if payload.get("reasoning_effort"):
        result["reasoning_effort"] = payload["reasoning_effort"]
    if len(json.dumps(result, ensure_ascii=False).encode()) > 4 * 1024 * 1024:
        raise BrainError(
            "ChatGPT browser prompt exceeds the executor's 4 MiB limit; compact the context"
        )
    return result


def browser_completion(text, tools, tool_choice=None):
    from kratos_agent.sdk.client import KratosCompletion, KratosToolCall

    if not isinstance(text, str) or not text.strip():
        raise BrainError("ChatGPT browser returned an empty response")
    if not tools or tool_choice == "none":
        return KratosCompletion(text=text)
    candidate = text.strip()
    lines = candidate.splitlines()
    if len(lines) >= 3 and lines[0].strip() in {"```", "```json"} and lines[-1].strip() == "```":
        candidate = "\n".join(lines[1:-1]).strip()
    required = tool_choice == "required" or isinstance(tool_choice, dict)
    try:
        try:
            body = json.loads(candidate)
        except json.JSONDecodeError:
            # Native tool APIs also permit final text when tool_choice is auto.
            # Malformed/embedded tool instructions still require correction and
            # can never be treated as successfully executed tools.
            # Older runtime prompts documented call:NAME{JSON}. Accept that
            # complete protocol too, subject to the identical schema checks.
            from .tool_calls import extract_tool_calls_from_text
            try:
                plain, parsed_calls = extract_tool_calls_from_text(candidate, strict=True)
            except BrainToolCallError as malformed:
                raise ValueError("Incomplete text tool call") from malformed
            if parsed_calls:
                body = {"text": plain, "tool_calls": [
                    {"name": call["name"], "arguments": call["args"]} for call in parsed_calls]}
            elif required or candidate.startswith(("{", "[")) or re.search(
                r'"tool_calls"\s*:|^\s*(?:call:|<tool_call|<function_call|functions\.)',
                candidate,
            ):
                raise ValueError("Invalid tool envelope")
            else:
                return KratosCompletion(text=text)
        if (
            not isinstance(body, dict)
            or set(body) != {"text", "tool_calls"}
            or not isinstance(body["text"], str)
            or not isinstance(body["tool_calls"], list)
        ):
            raise ValueError("Invalid envelope")
        available = {
            tool["function"]["name"]: tool["function"].get("parameters", {})
            for tool in tools
        }
        calls = []
        forced_name = tool_choice.get("function", {}).get("name") if isinstance(tool_choice, dict) else None
        if len(body["tool_calls"]) > 32:
            raise ValueError("Too many tool calls")
        for call in body["tool_calls"]:
            if (
                not isinstance(call, dict)
                or set(call) != {"name", "arguments"}
                or not isinstance(call["name"], str)
                or call["name"] not in available
                or (forced_name is not None and call["name"] != forced_name)
                or not isinstance(call["arguments"], dict)
            ):
                raise ValueError("Invalid tool")
            Draft202012Validator(available[call["name"]]).validate(call["arguments"])
            calls.append(
                KratosToolCall(
                    "call_" + uuid.uuid4().hex, call["name"], call["arguments"]
                )
            )
        if (required and not calls) or (not body["text"].strip() and not calls):
            raise ValueError("Empty result")
        return KratosCompletion(body["text"], calls, "tool_calls" if calls else "stop")
    except (ValueError, KeyError, TypeError, ValidationError, SchemaError) as exc:
        error = BrainToolCallError("The browser model returned an invalid local tool response; no tool was executed")
        error.correction = (
            'Return {"text":"your answer","tool_calls":[]} for a final answer, or '
            '{"text":"","tool_calls":[{"name":"REGISTERED_TOOL","arguments":{...}}]} to use a tool. '
            'Return one complete JSON object, using only registered names and schema-valid arguments. '
            'Use forward slashes in Windows file paths. Do not emit native, XML, DSML, or call: markup.'
        )
        if isinstance(exc, ValidationError):
            # Report the schema rule and field, never a value or upstream text.
            error.correction += " Argument schema violation: " + str(exc.validator) + " at " + ".".join(map(str, exc.absolute_path)) + "."
        raise error from exc


class ChatGPTWebAccounts:
    def __init__(self, store=None):
        self.store = store or account_store
        self._executor_workers = BrowserExecutorWorkers()

    def source(self, explicit=None):
        root = Path(
            explicit
            or os.getenv("KRATOS_OMNIROUTE_DIR")
            or Path(__file__).resolve().parents[3] / "services" / "omniroute"
        ).resolve()
        if (
            not (root / "open-sse/executors/chatgpt-web.ts").is_file()
            or not (root / "node_modules/tsx").is_dir()
        ):
            raise BrainError(
                "ChatGPT web needs the OmniRoute directory containing the executor and its installed Node dependencies; use --omniroute-dir"
            )
        return root

    def prepare_browser(self):
        """Installable connector for the user's ordinary Chrome or Edge profile."""
        with self.store.locked():
            state = self.store.read()
            changed = False
            token = state.get("browser_bridge_token")
            if not isinstance(token, str) or len(token) < 32:
                token = secrets.token_urlsafe(48)
                state["browser_bridge_token"] = token
                changed = True
            # Windows can reserve broad port ranges. Let the OS choose usable ports.
            with ExitStack() as sockets:
                for key in ("browser_bridge_port", "browser_control_port"):
                    blocked = False
                    if type(state.get(key)) is int and 1024 <= state[key] <= 65535:
                        import requests
                        with requests.Session() as local:
                            local.trust_env = False
                            endpoint = '/health' if key == 'browser_bridge_port' else '/status'
                            try:
                                reply = local.get(f'http://127.0.0.1:{state[key]}{endpoint}',
                                                  headers={'Authorization': 'Bearer ' + token}, timeout=0.4)
                                if reply.ok and reply.json().get('ready') is True:
                                    continue
                            except (requests.RequestException, ValueError):
                                pass
                        with socket.socket() as probe:
                            try:
                                probe.bind(('127.0.0.1', state[key]))
                                probe.listen(1)
                            except OSError as exc:
                                # A saved port can become reserved or be claimed
                                # by an unrelated socket while Studio is stopped.
                                blocked = (getattr(exc, 'winerror', None) in (10013, 10048)
                                           or exc.errno in (errno.EACCES, errno.EADDRINUSE) or isinstance(exc, PermissionError))
                    if (
                        type(state.get(key)) is not int
                        or not 1024 <= state[key] <= 65535
                        or blocked
                    ):
                        listener = sockets.enter_context(socket.socket())
                        listener.bind(("127.0.0.1", 0))
                        listener.listen(1)
                        state[key] = listener.getsockname()[1]
                        changed = True
                if changed:
                    self.store.write(state)
            port, control_port = (
                state["browser_bridge_port"],
                state["browser_control_port"],
            )
        register_sensitive_values(token)
        directory = self.store.root / "browser-extension"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        manifest = {
            "manifest_version": 3,
            "name": "Kratos browser connections",
            "version": "1.7.0",
            "description": "Collect and refresh website session cookies for local OmniRoute executors.",
            "permissions": ["cookies", "alarms", "storage"],
            "host_permissions": sorted({"http://127.0.0.1/*", *(
                pattern for provider in WEB_PROVIDERS.values() for domain in provider["domains"]
                for pattern in ("https://" + domain + "/*", "https://*." + domain + "/*"))}),
            "background": {"service_worker": "background.js"},
            "content_scripts": [
                {
                    "matches": [provider["url"].split("/", 3)[0] + "//" + provider["url"].split("/", 3)[2] + "/*" for provider in WEB_PROVIDERS.values()],
                    "js": ["content.js"],
                    "run_at": "document_idle",
                }
            ],
            "action": {
                "default_title": "Kratos connections",
                "default_popup": "popup.html",
            },
        }
        files = {
            "manifest.json": json.dumps(manifest, indent=2),
            "config.js": "const KRATOS_BROWSER = "
            + json.dumps(
                {
                    "token": token,
                    "endpoint": f"http://127.0.0.1:{port}",
                    "control": f"http://127.0.0.1:{control_port}",
                    "providers": WEB_PROVIDERS,
                }
            )
            + ";\n",
        }
        source_dir = Path(__file__).with_name("chatgpt_browser_extension")
        for name in (
            "background.js",
            "content.js",
            "popup.html",
            "popup.css",
            "popup.js",
        ):
            files[name] = (source_dir / name).read_text(encoding="utf-8")
        directories = [directory]
        legacy = state.get('legacy_extension_directory')
        expected_legacy = Path(os.getenv('LOCALAPPDATA') or Path.home() / 'AppData/Local') / 'KratosAgent/auth/browser-extension'
        if legacy and Path(legacy).resolve() == expected_legacy.resolve() and Path(legacy).is_dir():
            directories.append(Path(legacy))
        for install_dir in directories:
            for name, contents in files.items():
                target = install_dir / name
                if not target.exists() or target.read_text(encoding="utf-8") != contents:
                    target.write_text(contents, encoding="utf-8")
                    if os.name != "nt":
                        target.chmod(0o600)
        return {
            "token": token,
            "port": port,
            "control_port": control_port,
            "directory": str(directory),
            "files": sorted(files),
        }

    def run_bridge(self, request, source, timeout, cancel=None):
        if request.get("storage_state") is not None:
            return self._run_bridge({**request, "timeout": int(timeout * 1000)}, source, timeout, cancel)
        connection = self.prepare_browser()
        with self.session_lock(
            "regular-browser-connection", timeout, cancel
        ) as remaining:
            private_connection = {
                "token": connection["token"],
                "port": connection["port"],
                "timeout": int(remaining * 1000),
            }
            return self._run_bridge(
                {**request, "browser_connection": private_connection},
                source,
                remaining,
                cancel,
            )

    def _run_bridge(self, request, source, timeout, cancel=None):
        node = shutil.which("node")
        if not node:
            raise BrainError("Node.js is required for the ChatGPT browser executor")
        env = dict(os.environ)
        env["DATA_DIR"] = str(self.store.root / "web-executor-data")
        env["NODE_PATH"] = (
            str(source / "node_modules") + os.pathsep + env.get("NODE_PATH", "")
        )
        # Session data travels only through private pipes, never command arguments.
        command = [
            node, "--import", "tsx/esm",
            str(Path(__file__).with_name("chatgpt_web_bridge.mjs")),
            "--source", str(source),
        ]
        if (
            request.get("mode") == "complete"
            and request.get("provider_id", "chatgpt-web") == "chatgpt-web"
            and isinstance(request.get("account_id"), str)
            and request["account_id"]
            and isinstance(request.get("storage_state"), dict)
        ):
            output = self._executor_workers.request(
                request["account_id"], source, request,
                command=[*command, "--persistent"], cwd=source, env=env,
                timeout=timeout, cancel=cancel,
            )
            return self._decode_bridge_result(output, request)
        process = subprocess.Popen(
            command,
            cwd=source,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        started = time.monotonic()
        try:
            data = json.dumps(request, ensure_ascii=False).encode()
            while True:
                if cancel is not None and cancel.is_set():
                    # Let the extension abort the page operation and detach before
                    # the fallback below terminates this turn's private worker.
                    connection = request.get("browser_connection", {})
                    if connection:
                        import requests
                        with requests.Session() as local:
                            local.trust_env = False
                            try:
                                local.post(
                                    f"http://127.0.0.1:{connection['port']}/cancel",
                                    headers={"Authorization": "Bearer " + connection["token"]},
                                    timeout=0.5,
                                )
                                process.communicate(timeout=2.5)
                            except (requests.RequestException, subprocess.TimeoutExpired):
                                pass
                    raise BrainError("ChatGPT browser request cancelled")
                if time.monotonic() - started > timeout:
                    raise BrainTimeoutError(
                        "ChatGPT browser timed out; finish sign-in or verification in the browser"
                    )
                try:
                    output, _ = process.communicate(input=data, timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    data = None
            if process.returncode:
                raise BrainError(
                    "ChatGPT browser executor failed to start; check Node dependencies and the executor path"
                )
            return self._decode_bridge_result(output, request)

        finally:
            if process.poll() is None:
                import psutil

                try:
                    parent = psutil.Process(process.pid)
                    owned = [*parent.children(recursive=True), parent]
                    for child in reversed(owned):
                        try:
                            child.terminate()
                        except psutil.NoSuchProcess:
                            continue
                    _, alive = psutil.wait_procs(owned, timeout=2)
                    for child in alive:
                        try:
                            child.kill()
                        except psutil.NoSuchProcess:
                            continue
                except psutil.NoSuchProcess:
                    process.kill()
                process.wait(timeout=5)

    def _decode_bridge_result(self, output, request):
        try:
            result = json.loads(output)
        except (ValueError, UnicodeDecodeError) as exc:
            raise BrainError(
                "ChatGPT browser bridge returned an invalid result"
            ) from exc
        if not isinstance(result, dict):
            raise BrainError("ChatGPT browser bridge returned an invalid result")
        if result.get("error"):
            if result.get("status") == 429:
                raise BrainRateLimitError("ChatGPT browser usage limit reached")
            code = result.get("error")
            messages = {
                "sign_in_required": "Sign in to ChatGPT in the browser before using its models",
                "account_changed": "ChatGPT browser changed accounts; reconnect it",
                "account_model_catalog_unavailable": "ChatGPT did not return its account model catalog; reconnect or finish browser verification",
                "model_not_available_for_account": "The selected model is no longer advertised by this ChatGPT account",
                "browser_navigation_failed": "ChatGPT could not be reached by the local executor; check the network or proxy and retry",
                "browser_conversation_lost": "The saved website conversation is unavailable; start a new conversation to restore context",
                "cookie_only_unsupported": "This website executor requires an additional authorization credential; cookies alone are insufficient",
                "website_executor_unavailable": "This website has no supported cookie executor in this OmniRoute installation",
                "browser_turn_failed": "ChatGPT browser turn failed; check the account access or finish browser verification",
                "browser_module_unavailable": "ChatGPT's website request module changed or has not loaded; refresh the signed-in ChatGPT tab and retry",
                "browser_stream_incomplete": "ChatGPT's response stream did not contain a completed assistant reply; retry the request",
                "browser_request_invalid": "The website executor rejected this request's model, prompt or thinking setting",
                "empty_browser_response": "ChatGPT browser returned an empty response",
                "browser_extension_unavailable": "Load the Kratos browser extension in your regular browser and keep a signed-in ChatGPT tab open",
                "browser_tab_missing": "Open the selected provider's signed-in website tab in the browser containing the Kratos extension",
                "browser_debugger_unavailable": "The Kratos extension cannot attach to the website tab; close its developer tools and retry",
                "browser_draft_present": "ChatGPT has an unsent draft; open an empty ChatGPT chat before retrying",
                "browser_page_busy": "ChatGPT is already generating on the website; wait for it to finish before retrying",
                "browser_model_unavailable": "The selected model is unavailable in ChatGPT's website model picker; refresh the catalog and choose a supported model",
                "browser_effort_unavailable": "The selected thinking level is unavailable in ChatGPT's website; choose Low, Medium or High",
                "browser_submit_unavailable": "ChatGPT's message box is unavailable in the local executor; collect fresh cookies and retry",
                "browser_response_incomplete": "ChatGPT did not complete a new reply; check the signed-in tab for a usage limit or verification request",
            }
            failure = BrainError(
                messages.get(
                    code,
                    "ChatGPT cookie executor failed; retry once, or collect fresh session cookies if the website login has expired",
                )
                + (f" (HTTP {result['status']})" if code == 'browser_turn_failed' and type(result.get('status')) is int else '')
            )
            failure.code = code
            diagnostic = result.get("diagnostic")
            if isinstance(diagnostic, dict) and re.fullmatch(r"(?:executor|(?:chatgpt_cookie_executor|chatgpt_owned_turn|web_cookie_bridge)\.mjs:\d+:\d+)", str(diagnostic.get("location", ""))):
                failure.diagnostic = {"location": diagnostic["location"]}
            if isinstance(diagnostic, dict) and re.fullmatch(r"(?:ERR_[A-Z_]+|navigation_timeout)", str(diagnostic.get("network", ""))):
                failure.diagnostic = {"network": diagnostic["network"]}
            if result.get("phase") in {"navigation", "session", "model-selection", "effort-selection", "composer", "prompt-insertion", "submission", "response"}:
                failure.phase = result["phase"]
            provider_name = WEB_PROVIDERS.get(request.get("provider_id", "chatgpt-web"), {}).get("name", "Browser model")
            failure.args = (str(failure).replace("ChatGPT", provider_name),)
            raise failure
        result["storage_state"] = normalize_storage(result.get("storage_state"), request.get("provider_id", "chatgpt-web"))
        return result

    def login(self, *, source=None, provider="chatgpt-web", snapshot=None):
        if provider not in WEB_PROVIDERS:
            raise BrainError("Choose a supported browser provider")
        source = self.source(source)
        request = {"mode": "login", "provider_id": provider}
        if snapshot is not None:
            request.update({key: snapshot[key] for key in ("cookie_store_id", "user_agent") if key in snapshot})
            request["storage_state"] = normalize_storage(snapshot.get("storage_state"), provider)
        result = self.run_bridge(request, source, 330)
        subject = result.get("subject")
        if not isinstance(subject, str) or not subject:
            raise BrainError("ChatGPT browser did not confirm an account identity")
        identity = hashlib.sha256((provider + ":" + subject).encode()).hexdigest()[:24]
        result["storage_state"] = normalize_storage(result.get("storage_state"), provider)
        with self.store.locked():
            state = self.store.read()
            previous = state.setdefault("web_accounts", {}).get(identity, {})
            # One website login owns automatic refresh for each browser cookie store.
            for other_id, other in state["web_accounts"].items():
                if other_id != identity and other.get("provider_id", "chatgpt-web") == provider and other.get("cookie_store_id") == result.get("cookie_store_id", snapshot.get("cookie_store_id") if snapshot else None):
                    other["cookie_store_id"] = None
            state["web_accounts"][identity] = {
                **previous,
                **{
                    key: result[key]
                    for key in ("subject", "email", "models", "storage_state")
                    if key in result
                },
                "session_expired": False,
                "models_checked_at": time.time(),
                "source": str(source),
                "provider_id": provider,
                "cookie_store_id": result.get("cookie_store_id", snapshot.get("cookie_store_id") if snapshot else None),
                "user_agent": result.get("user_agent", snapshot.get("user_agent", "") if snapshot else ""),
                "cookies_checked_at": time.time(),
            }
            self.store.write(state)
        gateway_sync = self.sync_gateway_account(identity)
        return {
            "account_id": identity,
            "email": result.get("email", ""),
            "models": result.get("models", []),
            "selected": False,
            "gateway_sync": gateway_sync,
        }

    def status(self):
        state = self.store.read()
        return {
            "provider": state.get("provider", "gateway"),
            "active_account": state.get("active_web_account", ""),
            "accounts": [
                {
                    "id": key,
                    "email": value.get("email", ""),
                    "model": value.get("model", ""),
                    "connected": bool(value.get("storage_state")) and not value.get("session_expired"),
                }
                for key, value in state.get("web_accounts", {}).items()
            ],
        }

    def _record(self, account_id=None):
        state = self.store.read()
        key = account_id or state.get("active_web_account")
        record = state.get("web_accounts", {}).get(key)
        if not record or not record.get("storage_state"):
            raise BrainError(
                "Sign in with kratos-connect web-login before using browser models"
            )
        if record.get("session_expired"):
            raise BrainError("Browser session expired. Sign in normally on the website; the extension will refresh its cookies.")
        return key, record

    def sync_snapshot(self, provider, snapshot):
        """Refresh only an enabled binding; never restore a disconnected login."""
        if provider not in WEB_PROVIDERS or not isinstance(snapshot, dict) or not isinstance(snapshot.get("cookie_store_id"), str):
            raise BrainError("Invalid cookie refresh request")
        raw = snapshot.get("storage_state")
        if not isinstance(raw, dict) or not isinstance(raw.get("cookies"), list):
            raise BrainError("Invalid cookie refresh snapshot")
        validated = normalize_storage(raw, provider, allow_empty=True)
        valid = validated if validated["cookies"] else None
        if provider == "chatgpt-web" and not any(
            re.fullmatch(r"(?:__Secure-)?(?:next-auth|authjs)\.session-token(?:\.\d+)?", cookie["name"])
            for cookie in validated["cookies"]
        ):
            valid = None
        with self.store.locked():
            state = self.store.read()
            changed = 0
            updated_accounts = []
            for key, record in state.get("web_accounts", {}).items():
                if not record.get("storage_state") or record.get("provider_id", "chatgpt-web") != provider or record.get("cookie_store_id") != snapshot["cookie_store_id"]:
                    continue
                if valid is None:
                    record["session_expired"] = True
                else:
                    refreshed = dict(valid)
                    if not refreshed["origins"]:
                        refreshed["origins"] = record["storage_state"].get("origins", [])
                    record["storage_state"] = refreshed
                    record["session_expired"] = False
                    record["user_agent"] = snapshot.get("user_agent", record.get("user_agent", ""))
                record["cookies_checked_at"] = time.time()
                action = "expired" if valid is None else "sync"
                record["gateway_sync"] = {"synced": False, "pending": True, "action": action}
                updated_accounts.append(key)
                changed += 1
            if changed:
                self.store.write(state)
        for key in updated_accounts:
            self.sync_gateway_account(key)
        return {"updated": changed, "expired": valid is None}

    def sync_gateway_account(self, account_id):
        """Send vault credentials to the running local service; publish metadata only."""
        from .gateway_cookie_sync import sync_gateway_cookies
        action = "sync"
        try:
            with self.session_lock("gateway-cookie:" + account_id, 3):
                record = self.store.read().get("web_accounts", {}).get(account_id)
                if not record:
                    raise BrainError("Unknown browser account")
                previous = record.get("gateway_sync", {})
                action = previous.get("action") if previous.get("pending") else None
                action = action or ("disconnect" if not record.get("storage_state") else "expired" if record.get("session_expired") else "sync")
                result = sync_gateway_cookies(account_id, record, action)
        except BrainError:
            return {"synced": False, "pending": True, "action": action, "error": "OmniRoute cookie sync is already running. Retry in a moment."}
        with self.store.locked():
            state = self.store.read()
            current = state.get("web_accounts", {}).get(account_id)
            # An in-flight credential update must not mark a newer login, or a
            # concurrent disconnect, as successfully synchronized.
            if (current and current.get("storage_state") == record.get("storage_state")
                    and current.get("session_expired") == record.get("session_expired")
                    and current.get("user_agent") == record.get("user_agent")):
                current["gateway_sync"] = result
                self.store.write(state)
        return result

    def retry_gateway_sync(self, limit=2):
        """Recover the service hop without collecting credentials or fetching models."""
        attempted = 0
        for key, record in self.store.read().get("web_accounts", {}).items():
            status = record.get("gateway_sync", {})
            if not status.get("pending") and (status.get("synced") or not record.get("storage_state")):
                continue
            if time.time() - status.get("checked_at", 0) < 10:
                continue
            self.sync_gateway_account(key)
            attempted += 1
            if attempted >= limit:
                break
        return attempted

    def _save_refresh(self, key, record, result):
        if result.get("subject") != record["subject"]:
            raise BrainError(
                "ChatGPT browser changed accounts; sign in again before using this session"
            )
        if "storage_state" in result:
            result["storage_state"] = normalize_storage(result["storage_state"], record.get("provider_id", "chatgpt-web"))
        with self.store.locked():
            state = self.store.read()
            current = state.get("web_accounts", {}).get(key)
            if not current or not current.get("storage_state"):
                raise BrainError(
                    "ChatGPT browser account was disconnected during the request"
                )
            current.update(
                {
                    name: result[name]
                    for name in ("storage_state", "models")
                    if name in result and (name != "storage_state" or current["storage_state"] == record["storage_state"])
                }
            )
            current["models_checked_at"] = time.time()
            self.store.write(state)

    @contextmanager
    def session_lock(self, key, timeout, cancel=None):
        lock_path = self.store.root / (
            "web-session-"
            + hashlib.sha256(str(key).encode()).hexdigest()[:24]
            + ".lock"
        )
        self.store.root.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        with lock_path.open("a+b") as lock:
            while True:
                if cancel is not None and cancel.is_set():
                    raise BrainError("ChatGPT browser request cancelled")
                if time.monotonic() - started > timeout:
                    raise BrainTimeoutError("ChatGPT browser session is busy")
                try:
                    portalocker.lock(lock, portalocker.LOCK_EX | portalocker.LOCK_NB)
                    break
                except portalocker.LockException:
                    time.sleep(0.1)
            try:
                yield max(0.01, timeout - (time.monotonic() - started))
            finally:
                portalocker.unlock(lock)

    def models(self, account_id=None, *, timeout=60, refresh=True):
        key, record = self._record(account_id)
        if (
            not refresh
            and "models" in record
        ):
            return record["models"]
        with self.session_lock(key, timeout) as remaining:
            key, record = self._record(key)
            result = self.run_bridge(
                {
                    "mode": "models",
                    "subject": record["subject"],
                    "provider_id": record.get("provider_id", "chatgpt-web"),
                    "account_id": key,
                    "storage_state": record["storage_state"],
                    "user_agent": record.get("user_agent", ""),
                },
                self.source(record["source"]),
                remaining,
            )
            self._save_refresh(key, record, result)
            return result.get("models", [])

    def select(self, account_id, model, effort=None):
        metadata = next((item for item in self.models(account_id, refresh=False) if item["id"] == model), None)
        if metadata is None:
            raise BrainError(
                "Choose an account model supported by the ChatGPT web executor"
            )
        if effort is not None and effort not in metadata.get("effort_tiers", []):
            raise BrainError("This browser model does not support that thinking level")
        with self.store.locked():
            state = self.store.read()
            if (
                not state.get("web_accounts", {})
                .get(account_id, {})
                .get("storage_state")
            ):
                raise BrainError("ChatGPT browser account was disconnected")
            state["web_accounts"][account_id]["model"] = model
            state["web_accounts"][account_id]["reasoning_effort"] = effort
            provider = state["web_accounts"][account_id].get("provider_id", "chatgpt-web")
            state.update(provider="chatgpt-web" if provider == "chatgpt-web" else "browser-web", active_web_account=account_id)
            self.store.write(state)
        return {
            "provider": "chatgpt-web" if provider == "chatgpt-web" else "browser-web",
            "provider_id": provider,
            "reasoning_effort": effort,
            "model": model,
            "account_id": account_id,
            "access_verified": False,
        }

    def complete(self, client, payload, timeout, on_chunk=None, cancel=None, *, session_id=""):
        from .browser_conversation import (
            completed_cursor,
            conversation_key,
            prepare_conversation,
        )
        key = client.chatgpt_web_account_id
        with self.session_lock(key, timeout, cancel) as remaining:
            key, record = self._record(key)
            payload = dict(payload)
            if record.get("reasoning_effort"):
                payload.setdefault("reasoning_effort", record["reasoning_effort"])
            # Calls outside a runtime session never inherit someone else's chat.
            scope = conversation_key(key, session_id, payload["model"]) if session_id else uuid.uuid4().hex
            previous = self.store.read().get("browser_conversations", {}).get(scope, {})
            if previous.get("inflight"):
                previous = {}
            outgoing, cursor, continuing, include_tools = prepare_conversation(payload, previous)
            with self.store.locked():
                state = self.store.read()
                state.setdefault("browser_conversations", {})[scope] = dict(previous, inflight=True)
                self.store.write(state)
            request = {
                    "mode": "complete",
                    "subject": record["subject"],
                    "account_id": key,
                    "provider_id": record.get("provider_id", "chatgpt-web"),
                    "storage_state": record["storage_state"],
                    "user_agent": record.get("user_agent", ""),
                    "payload": browser_payload(outgoing, include_tools=include_tools),
                    "models": record.get("models"),
                    "requested_tools": payload.get("tools", []) if payload.get("tool_choice") != "none" else [],
                    "conversation": {"key": scope, "new": not continuing, **(previous.get("remote", {}) if continuing else {})},
                }
            started = time.monotonic()
            try:
                result = self.run_bridge(request, self.source(record["source"]), remaining, cancel)
            except BrainError as exc:
                if not continuing or getattr(exc, "code", None) != "browser_conversation_lost":
                    raise
                request["conversation"] = {"key": scope, "new": True}
                request["payload"] = browser_payload(payload)
                result = self.run_bridge(request, self.source(record["source"]), max(0.01, remaining - (time.monotonic() - started)), cancel)
            self._save_refresh(key, record, result)
            completion = None
            try:
                completion = browser_completion(result.get("text"), payload.get("tools", []), payload.get("tool_choice"))
            finally:
                if isinstance(result.get("conversation"), dict):
                    with self.store.locked():
                        state = self.store.read()
                        cursors = state.setdefault("browser_conversations", {})
                        cursors[scope] = completed_cursor(cursor, result, completion)
                        # Only cursor metadata is evicted; saved user sessions and
                        # provider conversations stay intact.
                        if len(cursors) > 1000:
                            oldest = min((k for k in cursors if k != scope), key=lambda k: cursors[k].get("updated_at", 0))
                            cursors.pop(oldest)
                        self.store.write(state)
            if on_chunk and completion.text:
                client._notify_chunk(on_chunk, completion.text)
            return completion

    def sign_out(self, account_id):
        with self.store.locked():
            state = self.store.read()
            record = state.get("web_accounts", {}).get(account_id)
            if not record:
                raise BrainError("Unknown ChatGPT browser account")
            record.pop("storage_state", None)
            record["gateway_sync"] = {"synced": False, "pending": True, "action": "disconnect"}
            self.store.write(state)
        self._executor_workers.close(account_id)
        gateway_sync = self.sync_gateway_account(account_id)
        return {
            "signed_out": True,
            "message": "Browser credentials removed from Kratos",
            "gateway_sync": gateway_sync,
        }


chatgpt_web_accounts = ChatGPTWebAccounts()
