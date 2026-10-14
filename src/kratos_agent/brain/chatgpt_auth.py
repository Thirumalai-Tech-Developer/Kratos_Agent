"""Official Sign in with ChatGPT: loopback OAuth, PKCE and verified identity."""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import jwt
import requests

from .account_store import account_store

ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
AUTHORIZE = ISSUER + "/api/accounts/authorize"
TOKEN = ISSUER + "/api/accounts/oauth/token"
PLAN_SCOPE = "chatgpt.tokens.use.direct"


class ChatGPTConnectionError(RuntimeError):
    pass


def _session():
    session = requests.Session()
    session.trust_env = False
    return session


def _json_request(session, method, url, **kwargs):
    try:
        response = session.request(method, url, **kwargs)
        if response.status_code != 200:
            raise ChatGPTConnectionError(
                f"ChatGPT connection request failed (HTTP {response.status_code}); reconnect the account if its permission expired"
            )
        body = response.json()
        if not isinstance(body, dict):
            raise TypeError("Invalid object")
        return body
    except (requests.RequestException, ValueError, TypeError) as exc:
        raise ChatGPTConnectionError(
            "ChatGPT connection request could not be completed"
        ) from exc


def _discovery(session):
    data = _json_request(
        session, "GET", ISSUER + "/.well-known/openid-configuration", timeout=15
    )
    if data.get("issuer") != ISSUER:
        raise ChatGPTConnectionError("ChatGPT identity issuer did not match")
    for field in ("jwks_uri", "revocation_endpoint"):
        url = urlparse(data.get(field, ""))
        if url.scheme != "https" or url.netloc != "auth.openai.com":
            raise ChatGPTConnectionError(
                "ChatGPT identity discovery returned an unexpected endpoint"
            )
    return data


def validate_identity(tokens, client_id, nonce, session):
    """Never trust decoded JWT claims without verifying signature and identity."""
    token = tokens.get("id_token")
    if not isinstance(token, str):
        raise ChatGPTConnectionError("ChatGPT sign-in did not return an identity token")
    try:
        discovery = _discovery(session)
        keys = _json_request(session, "GET", discovery["jwks_uri"], timeout=15).get(
            "keys", []
        )
        header = jwt.get_unverified_header(token)
        key = next(
            k
            for k in keys
            if k.get("kid") == header.get("kid") and k.get("kty") == "RSA"
        )
        claims = jwt.decode(
            token,
            jwt.PyJWK.from_dict(key, algorithm="RS256").key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=ISSUER,
            leeway=5,
            options={"require": ["sub", "exp", "iat", "nonce"]},
        )
        if (
            not isinstance(claims["sub"], str)
            or not claims["sub"]
            or not secrets.compare_digest(str(claims["nonce"]), nonce)
        ):
            raise ValueError("Identity mismatch")
        return claims
    except (jwt.PyJWTError, ValueError, StopIteration, KeyError, TypeError) as exc:
        raise ChatGPTConnectionError("ChatGPT identity verification failed") from exc


def _apply_tokens(record, tokens, *, refresh=False):
    scope = tokens.get("scope")
    scopes = (
        scope.split()
        if isinstance(scope, str)
        else record.get("scopes", [])
        if refresh
        else []
    )
    if PLAN_SCOPE not in scopes:
        raise ChatGPTConnectionError(
            "ChatGPT plan usage was not authorized; reconnect and enable plan usage"
        )
    if (
        not tokens.get("access_token")
        or str(tokens.get("token_type", "")).lower() != "bearer"
    ):
        raise ChatGPTConnectionError(
            "ChatGPT sign-in did not return a bearer credential"
        )
    try:
        lifetime = int(tokens["expires_in"])
        if lifetime <= 0:
            raise ValueError("Expired token")
    except (KeyError, TypeError, ValueError) as exc:
        raise ChatGPTConnectionError("ChatGPT credential expiry was missing") from exc
    result = {
        **record,
        "access_token": tokens["access_token"],
        "scopes": scopes,
        "expires_at": time.time() + lifetime,
    }
    for key in ("refresh_token", "id_token"):
        if tokens.get(key):
            result[key] = tokens[key]
    from kratos_agent.core.archive import register_sensitive_values

    register_sensitive_values(
        *(result.get(k, "") for k in ("access_token", "refresh_token", "id_token"))
    )
    return result


class ChatGPTAccounts:
    def __init__(self, store=None, session=None):
        self.store = store or account_store
        self.session = session or _session()
        self.attempts = {}
        self.lock = threading.RLock()

    def status(self):
        state = self.store.read()
        return {
            "provider": state.get("provider", "gateway"),
            "active_account": state.get("active_account", ""),
            "accounts": [
                {
                    "id": key,
                    "email": r.get("email", ""),
                    "label": r.get("label", key[:8]),
                    "model": r.get("model", ""),
                    "connected": bool(r.get("refresh_token") or r.get("access_token")),
                }
                for key, r in state["accounts"].items()
            ],
            "credential_storage": "Windows user protection (DPAPI)"
            if __import__("os").name == "nt"
            else "Owner-only user directory",
        }

    def start_login(self, account_id=None, *, open_browser=False):
        with self.lock:
            if any(
                a["status"] in {"pending", "exchanging"} for a in self.attempts.values()
            ):
                raise ChatGPTConnectionError("A ChatGPT sign-in is already pending")
            self.attempts = {
                k: a
                for k, a in self.attempts.items()
                if a["created"] > time.time() - 900
            }
            state = self.store.read()
            existing = state["accounts"].get(account_id) if account_id else None
            if account_id and existing is None:
                raise ChatGPTConnectionError("Unknown ChatGPT account registration")
            attempt_id = secrets.token_urlsafe(24)
            attempt = {
                "status": "pending",
                "created": time.time(),
                "state": secrets.token_urlsafe(32),
                "nonce": secrets.token_urlsafe(32),
                "verifier": secrets.token_urlsafe(48),
                "client_id": existing["client_id"]
                if existing
                else "dynamic_agent_client",
                "account_id": account_id,
                "existing": existing,
                "error": "",
            }
            self.attempts[attempt_id] = attempt

        manager = self

        class Callback(BaseHTTPRequestHandler):
            def log_message(self, *_):
                # HTTP callback queries contain an authorization code; record
                # only an operational event without the URL or request arguments.
                logging.getLogger(__name__).debug(
                    "ChatGPT loopback HTTP request handled"
                )

            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path != "/auth/callback":
                    self.send_error(404)
                    return
                try:
                    manager.finish_login(attempt_id, parse_qs(parsed.query))
                    message, status = (
                        "ChatGPT connected to Kratos. You can close this tab and select a model in Kratos.",
                        200,
                    )
                except ChatGPTConnectionError as exc:
                    message, status = str(exc), 400
                payload = message.encode()
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        try:
            server = ThreadingHTTPServer(("127.0.0.1", 0), Callback)
        except OSError as exc:
            attempt["status"], attempt["error"] = (
                "failed",
                "Could not open the ChatGPT loopback callback",
            )
            raise ChatGPTConnectionError(attempt["error"]) from exc
        server.daemon_threads = True
        attempt["redirect_uri"] = f"http://127.0.0.1:{server.server_port}/auth/callback"
        params = {
            "client_id": attempt["client_id"],
            "ext_agent_host_id": self.store.host_id(),
            "response_type": "code",
            "redirect_uri": attempt["redirect_uri"],
            "scope": "openid profile email offline_access resource.invoke "
            + PLAN_SCOPE,
            "resource": RESOURCE,
            "state": attempt["state"],
            "nonce": attempt["nonce"],
            "code_challenge_method": "S256",
            "code_challenge": base64.urlsafe_b64encode(
                hashlib.sha256(attempt["verifier"].encode()).digest()
            )
            .rstrip(b"=")
            .decode(),
        }
        if existing:
            # No ID token in a browser-visible URL or diagnostics. Account choice
            # is confirmed against the verified identity after authorization.
            if existing.get("email"):
                params["login_hint"] = existing["email"]
        else:
            params["agent_name_hint"] = "Kratos Agent"
        url = AUTHORIZE + "?" + urlencode(params)

        def listen():
            server.timeout = 0.5
            try:
                while attempt["status"] == "exchanging" or (
                    attempt["status"] == "pending"
                    and time.time() - attempt["created"] < 300
                ):
                    server.handle_request()
                if attempt["status"] == "pending":
                    attempt["status"], attempt["error"] = (
                        "expired",
                        "ChatGPT sign-in expired; try again",
                    )
            finally:
                server.server_close()
                for key in ("state", "nonce", "verifier", "existing"):
                    attempt.pop(key, None)

        threading.Thread(
            target=listen, name="kratos-chatgpt-signin", daemon=True
        ).start()
        if open_browser and not webbrowser.open(url):
            attempt["status"], attempt["error"] = (
                "failed",
                "Could not open ChatGPT sign-in; use Continue with ChatGPT in Operations",
            )
            raise ChatGPTConnectionError(attempt["error"])
        return {"attempt_id": attempt_id, "authorization_url": url, "status": "pending"}

    def login_status(self, attempt_id):
        with self.lock:
            attempt = self.attempts.get(attempt_id)
            if attempt is None:
                raise ChatGPTConnectionError("Unknown or expired ChatGPT sign-in")
            return {
                "status": attempt["status"],
                "error": attempt.get("error", ""),
                "account_id": attempt.get("connected_account", ""),
            }

    def finish_login(self, attempt_id, query):
        with self.lock:
            attempt = self.attempts.get(attempt_id)
            if (
                not attempt
                or attempt["status"] != "pending"
                or time.time() - attempt["created"] >= 300
            ):
                raise ChatGPTConnectionError(
                    "ChatGPT sign-in expired or was already used"
                )

            def one(key):
                values = query.get(key, [])
                return values[0] if len(values) == 1 else ""

            if not secrets.compare_digest(one("state"), attempt["state"]):
                raise ChatGPTConnectionError("ChatGPT callback state did not match")
            attempt["status"] = "exchanging"
            try:
                if one("error"):
                    raise ChatGPTConnectionError(
                        "ChatGPT sign-in was declined; no account was changed"
                    )
                client_id = one("client_id") or attempt["client_id"]
                if client_id == "dynamic_agent_client" or (
                    attempt["existing"] and client_id != attempt["client_id"]
                ):
                    raise ChatGPTConnectionError(
                        "ChatGPT registration client did not match"
                    )
                if not one("code"):
                    raise ChatGPTConnectionError(
                        "ChatGPT sign-in did not return a code"
                    )
                tokens = _json_request(
                    self.session,
                    "POST",
                    TOKEN,
                    data={
                        "grant_type": "authorization_code",
                        "client_id": client_id,
                        "code": one("code"),
                        "code_verifier": attempt["verifier"],
                        "redirect_uri": attempt["redirect_uri"],
                        "resource": RESOURCE,
                    },
                    timeout=20,
                )
                claims = validate_identity(
                    tokens, client_id, attempt["nonce"], self.session
                )
                existing = attempt["existing"] or {}
                if existing and claims["sub"] != existing["subject"]:
                    raise ChatGPTConnectionError(
                        "ChatGPT signed in to a different account; add it as a new account"
                    )
                identity = hashlib.sha256(
                    f"{ISSUER}:{client_id}:{claims['sub']}".encode()
                ).hexdigest()[:24]
                record = _apply_tokens(
                    {
                        **existing,
                        "client_id": client_id,
                        "subject": claims["sub"],
                        "issuer": ISSUER,
                        "email": claims.get("email", ""),
                        "label": f"{claims.get('email') or 'ChatGPT account'} · {identity[:8]}",
                    },
                    tokens,
                )
                with self.store.locked():
                    saved = self.store.read()
                    saved["accounts"][identity] = record
                    if not saved.get("active_account"):
                        saved["active_account"] = identity
                    self.store.write(saved)
                attempt["connected_account"], attempt["status"] = identity, "completed"
            except ChatGPTConnectionError as exc:
                attempt["status"], attempt["error"] = "failed", str(exc)
                raise
            except Exception as exc:
                attempt["status"], attempt["error"] = (
                    "failed",
                    "ChatGPT sign-in could not be saved",
                )
                raise ChatGPTConnectionError(attempt["error"]) from exc

    def access_token(self, account_id=None):
        with self.store.locked():
            state = self.store.read()
            account_id = account_id or state.get("active_account")
            record = state["accounts"].get(account_id)
            if not record or not record.get("access_token"):
                raise ChatGPTConnectionError(
                    "Connect a ChatGPT account in Operations before using its models"
                )
            if record.get("expires_at", 0) <= time.time() + 60:
                if not record.get("refresh_token"):
                    raise ChatGPTConnectionError(
                        "ChatGPT sign-in expired; reconnect the account"
                    )
                tokens = _json_request(
                    self.session,
                    "POST",
                    TOKEN,
                    data={
                        "grant_type": "refresh_token",
                        "client_id": record["client_id"],
                        "refresh_token": record["refresh_token"],
                        "resource": RESOURCE,
                    },
                    timeout=20,
                )
                record = _apply_tokens(record, tokens, refresh=True)
                state["accounts"][account_id] = record
                self.store.write(state)
            return record["access_token"]

    def models(self, account_id=None, timeout=10):
        token = self.access_token(account_id)
        body = _json_request(
            self.session,
            "GET",
            RESOURCE + "/models",
            headers={"Authorization": "Bearer " + token},
            timeout=timeout,
        )
        entries = body.get("models")
        if not isinstance(entries, list):
            raise ChatGPTConnectionError("ChatGPT returned an unexpected model catalog")
        return [
            {**item, "id": item["slug"]}
            for item in entries
            if isinstance(item, dict)
            and item.get("visibility") == "list"
            and isinstance(item.get("slug"), str)
            and item["slug"]
        ]

    def select(self, account_id, model):
        if not any(m["id"] == model for m in self.models(account_id)):
            raise ChatGPTConnectionError(
                "Choose a model advertised by this ChatGPT account"
            )
        with self.store.locked():
            state = self.store.read()
            record = state["accounts"].get(account_id)
            if not record or not record.get("access_token"):
                raise ChatGPTConnectionError("The ChatGPT account was disconnected")
            record["model"] = model
            state["active_account"], state["provider"] = account_id, "chatgpt"
            self.store.write(state)
        return {
            "provider": "chatgpt",
            "model": model,
            "account_id": account_id,
            "access_verified": False,
        }

    def use_gateway(self):
        with self.store.locked():
            state = self.store.read()
            state["provider"] = "gateway"
            self.store.write(state)
        return {"provider": "gateway"}

    def sign_out(self, account_id):
        confirmed = True
        with self.store.locked():
            state = self.store.read()
            record = state["accounts"].get(account_id)
            if not record:
                raise ChatGPTConnectionError("Unknown ChatGPT account registration")
            if record.get("refresh_token"):
                try:
                    endpoint = _discovery(self.session)["revocation_endpoint"]
                    confirmed = (
                        self.session.post(
                            endpoint,
                            data={
                                "token": record["refresh_token"],
                                "token_type_hint": "refresh_token",
                                "client_id": record["client_id"],
                            },
                            timeout=15,
                        ).status_code
                        == 200
                    )
                except (ChatGPTConnectionError, requests.RequestException):
                    confirmed = False
            for key in (
                "access_token",
                "refresh_token",
                "id_token",
                "expires_at",
                "scopes",
            ):
                record.pop(key, None)
            self.store.write(state)
        return {
            "signed_out": True,
            "revocation_confirmed": confirmed,
            "message": "Signed out"
            if confirmed
            else "Signed out locally; remote revocation was not confirmed. Disconnect Kratos in ChatGPT Settings.",
        }


chatgpt_accounts = ChatGPTAccounts()


def connection_main():
    """Browser sign-in for local use, independent of the web passcode."""
    import argparse
    import json

    from .config import BrainError

    parser = argparse.ArgumentParser(
        description="Connect Kratos using OmniRoute's chatgpt-web.ts browser executor"
    )
    parser.add_argument(
        "command",
        choices=[
            "login",
            "status",
            "models",
            "select",
            "signout",
            "gateway",
            "browser-setup",
            "browser",
            "web-login",
            "web-status",
            "web-models",
            "web-select",
            "web-signout",
        ],
    )
    from .web_providers import WEB_PROVIDERS
    parser.add_argument("--account", help="Saved browser account registration ID")
    parser.add_argument(
        "--provider",
        choices=[*WEB_PROVIDERS, "chatgpt"],
        default="chatgpt-web",
        help="Website for cookie connection; chatgpt selects official OAuth",
    )
    parser.add_argument(
        "--model", help="Exact model ID advertised by the selected account"
    )
    parser.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max", "minimal", "none"],
                        help="Thinking level, when the selected model supports it")
    parser.add_argument(
        "--omniroute-dir", help="OmniRoute source directory containing chatgpt-web.ts"
    )
    args = parser.parse_args()
    if args.provider in WEB_PROVIDERS and args.command in {
        "login",
        "status",
        "models",
        "select",
        "signout",
    }:
        args.command = "web-" + args.command
    try:
        if args.command in {"browser-setup", "browser"}:
            from .chatgpt_browser_control import ensure_browser_control
            from .chatgpt_web import chatgpt_web_accounts

            setup = chatgpt_web_accounts.prepare_browser()
            controller = ensure_browser_control(
                chatgpt_web_accounts, source=args.omniroute_dir
            )
            result = {
                "extension_directory": setup["directory"],
                "extension_files": setup["files"],
                "panel_running": controller["running"],
                "instructions": "In your regular Chrome or Edge, open its Extensions page, enable Developer mode, and Load unpacked from this directory. If already loaded, click Reload. Refresh the website tab, pin Kratos, choose the website and click Connect.",
            }
            if args.command == "browser":
                webbrowser.open(WEB_PROVIDERS.get(args.provider, WEB_PROVIDERS["chatgpt-web"])["url"])
        elif args.command.startswith("web-"):
            from .chatgpt_web import chatgpt_web_accounts

            if args.command == "web-login":
                provider = WEB_PROVIDERS.get(args.provider, WEB_PROVIDERS["chatgpt-web"])
                setup = chatgpt_web_accounts.prepare_browser()
                print(
                    "Use your regular Chrome or Edge and sign in to " + provider["name"] + " normally.\n"
                    "Load the Kratos extension once from: " + setup["directory"] + "\n"
                    "Refresh the signed-in website tab after loading the extension. Credentials stay outside the project.",
                    flush=True,
                )
                webbrowser.open(provider["url"].rstrip("/"))
                options = {"source": args.omniroute_dir}
                if args.provider in WEB_PROVIDERS and args.provider != "chatgpt-web":
                    options["provider"] = args.provider
                result = chatgpt_web_accounts.login(**options)
            elif args.command == "web-status":
                result = chatgpt_web_accounts.status()
            elif args.command == "web-models":
                result = chatgpt_web_accounts.models(args.account)
            elif args.command == "web-select":
                if not args.account or not args.model:
                    parser.error("web-select requires --account and --model")
                print(
                    "Finish active Kratos tasks and restart Studio after selecting a browser model.",
                    flush=True,
                )
                result = chatgpt_web_accounts.select(args.account, args.model, effort=args.effort)
            else:
                if not args.account:
                    parser.error("web-signout requires --account")
                result = chatgpt_web_accounts.sign_out(args.account)
        elif args.command == "login":
            login = chatgpt_accounts.start_login(args.account, open_browser=True)
            print(
                "ChatGPT sign-in opened in your browser. Complete authorization to connect Kratos.",
                flush=True,
            )
            while True:
                status = chatgpt_accounts.login_status(login["attempt_id"])
                if status["status"] not in {"pending", "exchanging"}:
                    if status["status"] != "completed":
                        raise ChatGPTConnectionError(
                            status["error"] or "ChatGPT sign-in ended"
                        )
                    break
                time.sleep(0.5)
            result = {
                "connection": chatgpt_accounts.status(),
                "models": [
                    {
                        "id": item["id"],
                        "display_name": item.get("display_name", item["id"]),
                    }
                    for item in chatgpt_accounts.models(status["account_id"])
                ],
            }
        elif args.command == "status":
            result = chatgpt_accounts.status()
        elif args.command == "models":
            result = [
                {"id": item["id"], "display_name": item.get("display_name", item["id"])}
                for item in chatgpt_accounts.models(args.account)
            ]
        elif args.command == "select":
            if not args.account or not args.model:
                parser.error(
                    "select requires --account and --model; finish active jobs first"
                )
            result = chatgpt_accounts.select(args.account, args.model)
        elif args.command == "signout":
            if not args.account:
                parser.error("signout requires --account; finish active jobs first")
            result = chatgpt_accounts.sign_out(args.account)
        else:
            result = chatgpt_accounts.use_gateway()
        print(json.dumps(result, indent=2, ensure_ascii=True))
    except (ChatGPTConnectionError, BrainError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    connection_main()
