"""Credential-only hop from the protected vault to the local OmniRoute service."""
from __future__ import annotations

import os
import time
from urllib.parse import urlparse

import requests


def sync_gateway_cookies(account_id: str, record: dict, action: str = "sync") -> dict:
    failed = {"synced": False, "pending": True, "action": action,
              "checked_at": time.time(), "error": "OmniRoute cookie sync is unavailable. Start Kratos Studio and retry sync."}
    base = os.getenv("KRATOS_GATEWAY_URL", "")
    token = os.getenv("OMNIROUTE_INTERNAL_SERVICE_TOKEN", "")
    try:
        target = urlparse(base)
        if (not token or target.scheme != "http" or target.hostname not in {"127.0.0.1", "localhost", "::1"}
                or target.username or target.password or target.path not in {"", "/"} or target.query or target.fragment):
            return failed
        _ = target.port  # Reject malformed ports before constructing a request.
    except ValueError:
        return failed
    payload = {"provider": record.get("provider_id", "chatgpt-web"), "account_id": account_id, "action": action}
    if action == "sync":
        if not record.get("storage_state") or record.get("session_expired"):
            return {**failed, "error": "Collect a current website login before syncing cookies to OmniRoute."}
        payload.update(storage_state=record["storage_state"], user_agent=record.get("user_agent", ""),
                       cookie_store_id=record.get("cookie_store_id"))
    with requests.Session() as local:
        local.trust_env = False  # Never send service auth or cookies through a user/system proxy.
        try:
            response = local.post(base.rstrip("/") + "/api/kratos/browser-cookies", json=payload,
                                  headers={"x-omniroute-internal-service-token": token},
                                  timeout=(0.5, 2.5), allow_redirects=False)
            body = response.json() if response.ok else {}
            if response.ok and isinstance(body, dict) and body.get("synced") is True:
                provider = body.get("provider")
                expected = "chatgpt-web-codex" if payload["provider"] == "chatgpt-web" else payload["provider"]
                if provider == expected and body.get("action") == action and body.get("usage") in {"native_codex_only", "chat_completions"}:
                    return {"synced": True, "pending": False, "action": action, "provider": provider,
                            "usage": body["usage"], "enabled": body.get("enabled") is True,
                            "connection_id": body.get("connection_id"), "checked_at": time.time(), "error": ""}
            if response.status_code in {401, 403}:
                failed["error"] = "OmniRoute rejected the local service credential. Restart Kratos Studio and retry sync."
            elif response.status_code == 409:
                failed["error"] = "OmniRoute account is restricted. Cookie refresh cannot remove that restriction."
            elif response.status_code in {400, 413}:
                failed["error"] = "OmniRoute could not accept these website cookies. Collect the login again."
        except (requests.RequestException, ValueError, TypeError):
            pass  # Raw transport/provider errors must never enter logs or the popup.
    return failed
