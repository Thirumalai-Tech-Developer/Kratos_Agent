#!/usr/bin/env python3
"""
ANTIGRAVITY MULTI-ACCOUNT OPENAI-COMPATIBLE GATEWAY
===================================================

Single API point in front of multiple Antigravity/AGY OAuth accounts.

Features
--------
- OpenAI-compatible:
    POST /v1/chat/completions
    GET  /v1/models
    GET  /health
- Multiple AGY/Antigravity OAuth accounts
- Automatic OAuth access-token refresh
- Automatic Google Cloud Code project discovery
- Automatic account fallback on:
    429 / rate limit
    quota exceeded / exhausted
    capacity / temporary upstream failures
    relevant 5xx
- Local account cooldown tracking
- Custom/global instruction (system prompt)
- Per-request system instruction
- Per-request `system_instruction` convenience field
- Streaming SSE (`stream=true`)
- Non-streaming JSON responses
- Simple local API-key protection
- No third-party Python packages required

IMPORTANT
---------
accounts.json contains live OAuth credentials. Keep it private.

This gateway reproduces the AGY/Antigravity request flow found in the
user-provided OmniRoute source:
- AGY uses the `cli` client profile
- project discovery uses `v1internal:loadCodeAssist`
- generation uses `v1internal:streamGenerateContent?alt=sse`
- OAuth refresh uses Google's token endpoint

Run
---
    python antigravity_gateway.py

Then point an OpenAI-compatible client at:

    http://127.0.0.1:8000/v1

Example
-------
    from openai import OpenAI

    client = OpenAI(
        base_url="http://127.0.0.1:8000/v1",
        api_key="local-key"
    )

    response = client.chat.completions.create(
        model="gemini-3.6-flash-high",
        messages=[
            {"role": "user", "content": "Explain transformers."}
        ]
    )

    print(response.choices[0].message.content)

Configuration files
-------------------
accounts.json
gateway_config.json

Recommended gateway_config.json:

{
  "host": "127.0.0.1",
  "port": 8000,
  "api_key": "local-key",
  "custom_instruction": "You are a helpful assistant.",
  "max_output_tokens": 8192,
  "cooldown_default_seconds": 60,
  "max_account_attempts": 0
}

`max_account_attempts`:
  0 = try every available account
  N = try at most N accounts

accounts.json example:

{
  "accounts": [
    {
      "name": "account1",
      "email": "one@gmail.com",
      "access_token": "YOUR_ACCESS_TOKEN",
      "refresh_token": "YOUR_REFRESH_TOKEN",
      "expires_at": null,
      "project_id": null
    }
  ]
}
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
ACCOUNTS_FILE = BASE_DIR / "accounts.json"
CONFIG_FILE = BASE_DIR / "gateway_config.json"
CURRENT_ACCOUNT_FILE = BASE_DIR / "current_account.json"

RUNTIME_BASE_URLS = [
    "https://daily-cloudcode-pa.googleapis.com",
    "https://cloudcode-pa.googleapis.com",
]
BOOTSTRAP_BASE_URLS = [
    "https://cloudcode-pa.googleapis.com",
]

LOAD_CODE_ASSIST_PATH = "/v1internal:loadCodeAssist"
FETCH_AVAILABLE_MODELS_PATH = "/v1internal:fetchAvailableModels"
STREAM_GENERATE_PATH = "/v1internal:streamGenerateContent?alt=sse"

TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo?alt=json"

# OmniRoute source pins the native Antigravity identity to this platform token.
OS_TYPE = "darwin"
ARCH = "arm64"

DEFAULT_AGY_VERSION = "1.1.0"

# Model catalog present in the supplied source.
PUBLIC_MODELS = [
    "gemini-3.6-flash-high",
    "gemini-3.6-flash-medium",
    "gemini-3.6-flash-low",
    "claude-opus-4-6-thinking",
    "claude-sonnet-4-6",
    "gemini-pro-agent",
    "gemini-3.1-pro-low",
    "gemini-3-flash-agent",
    "gemini-3.5-flash-low",
    "gemini-3.5-flash-extra-low",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-thinking",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gpt-oss-120b-medium",
]

DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 8000,
    "api_key": "local-key",
    "custom_instruction": "",
    "max_output_tokens": 8192,
    "cooldown_default_seconds": 60,
    "max_account_attempts": 0,
    "request_timeout_seconds": 600,
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class GatewayError(RuntimeError):
    pass


class UpstreamHTTPError(GatewayError):
    def __init__(
        self,
        status: int,
        message: str,
        retry_after: Optional[int] = None,
    ):
        self.status = status
        self.retry_after = retry_after
        super().__init__(message)


# ---------------------------------------------------------------------------
# JSON / config
# ---------------------------------------------------------------------------

def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GatewayError(f"Invalid JSON in {path}: {exc}") from exc


def write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(path)


def ensure_config_file() -> Dict[str, Any]:
    config = read_json(CONFIG_FILE, {})
    if not isinstance(config, dict):
        raise GatewayError(f"{CONFIG_FILE} must contain a JSON object.")

    merged = dict(DEFAULT_CONFIG)
    merged.update(config)

    if not CONFIG_FILE.exists():
        write_json(CONFIG_FILE, merged)

    return merged


# ---------------------------------------------------------------------------
# Account model
# ---------------------------------------------------------------------------

@dataclass
class Account:
    name: str
    email: str = ""
    access_token: str = ""
    refresh_token: str = ""
    expires_at: Optional[str] = None
    project_id: Optional[str] = None
    token_type: str = "Bearer"
    auth_method: str = "consumer"
    client_profile: str = "cli"
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Account":
        known = {
            "name",
            "email",
            "access_token",
            "refresh_token",
            "expires_at",
            "project_id",
            "token_type",
            "auth_method",
            "client_profile",
        }

        return cls(
            name=str(data.get("name") or data.get("email") or "account"),
            email=str(data.get("email") or ""),
            access_token=str(data.get("access_token") or ""),
            refresh_token=str(data.get("refresh_token") or ""),
            expires_at=data.get("expires_at"),
            project_id=data.get("project_id"),
            token_type=str(data.get("token_type") or "Bearer"),
            auth_method=str(data.get("auth_method") or "consumer"),
            client_profile=str(data.get("client_profile") or "cli"),
            extra={k: v for k, v in data.items() if k not in known},
        )

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "name": self.name,
            "email": self.email,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "project_id": self.project_id,
            "token_type": self.token_type,
            "auth_method": self.auth_method,
            "client_profile": self.client_profile,
        }
        result.update(self.extra)
        return result


class AccountStore:
    def __init__(self):
        self.accounts: Dict[str, Account] = {}
        self.load()

    def load(self) -> None:
        raw = read_json(ACCOUNTS_FILE, {"accounts": []})
        rows = raw.get("accounts", []) if isinstance(raw, dict) else raw

        if not isinstance(rows, list):
            raise GatewayError(
                f"{ACCOUNTS_FILE} must contain {{\"accounts\": [...]}}"
            )

        self.accounts = {}
        for row in rows:
            if isinstance(row, dict):
                account = Account.from_dict(row)
                self.accounts[account.name] = account

    def save(self) -> None:
        write_json(
            ACCOUNTS_FILE,
            {
                "accounts": [
                    a.to_dict() for a in self.accounts.values()
                ]
            },
        )

    def current_name(self) -> Optional[str]:
        raw = read_json(CURRENT_ACCOUNT_FILE, {})
        if isinstance(raw, dict):
            return raw.get("name")
        return None

    def set_current(self, name: str) -> None:
        if name not in self.accounts:
            raise GatewayError(f"Account not found: {name}")
        write_json(CURRENT_ACCOUNT_FILE, {"name": name})

    def current(self) -> Account:
        name = self.current_name()

        if name and name in self.accounts:
            return self.accounts[name]

        if not self.accounts:
            raise GatewayError(
                f"No accounts configured in {ACCOUNTS_FILE}"
            )

        first = next(iter(self.accounts.values()))
        self.set_current(first.name)
        return first


# ---------------------------------------------------------------------------
# Antigravity client identity / HTTP
# ---------------------------------------------------------------------------

def get_agy_version() -> str:
    for command in (["agy", "--version"], ["agy", "-V"]):
        try:
            import subprocess
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except Exception:
            continue

        value = (result.stdout or result.stderr or "").strip()
        match = re.search(
            r"(\d+\.\d+\.\d+(?:[-+._][A-Za-z0-9.-]+)?)",
            value,
        )
        if match:
            return match.group(1)

    return DEFAULT_AGY_VERSION


def client_user_agent(account: Account) -> str:
    version = get_agy_version()
    return (
        f"antigravity/cli/{version} "
        f"(aidev_client; os_type={OS_TYPE}; arch={ARCH}; "
        f"auth_method={account.auth_method or 'consumer'})"
    )


def content_headers(account: Account) -> Dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "User-Agent": client_user_agent(account),
    }

    if account.access_token:
        headers["Authorization"] = (
            f"{account.token_type or 'Bearer'} "
            f"{account.access_token}"
        )

    return headers


def parse_retry_after_seconds(value: Optional[str]) -> Optional[int]:
    if not value:
        return None

    value = value.strip()

    if value.isdigit():
        return max(1, int(value))

    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(value)
        return max(1, int(dt.timestamp() - time.time()))
    except Exception:
        return None


def extract_retry_seconds(message: str) -> Optional[int]:
    patterns = [
        r"retry[- ]after[^\d]*(\d+)",
        r"resets?\s+(?:after|in)\s+(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?",
    ]

    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if not match:
            continue

        groups = match.groups()

        if len(groups) == 1:
            return max(1, int(groups[0]))

        hours = int(groups[0] or 0)
        minutes = int(groups[1] or 0)
        seconds = int(groups[2] or 0)
        total = hours * 3600 + minutes * 60 + seconds

        if total:
            return total

    return None


def request_json(
    url: str,
    *,
    method: str,
    headers: Dict[str, str],
    body: Optional[Dict[str, Any]] = None,
    timeout: int = 60,
) -> Dict[str, Any]:
    payload = None

    if body is not None:
        payload = json.dumps(body).encode("utf-8")

    request = Request(
        url,
        data=payload,
        headers=headers,
        method=method,
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}

    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")

        retry_after = parse_retry_after_seconds(
            exc.headers.get("Retry-After")
        )

        if retry_after is None:
            retry_after = extract_retry_seconds(raw)

        raise UpstreamHTTPError(
            exc.code,
            f"HTTP {exc.code}: {raw[:5000]}",
            retry_after,
        ) from exc

    except URLError as exc:
        raise GatewayError(f"Network error calling {url}: {exc}") from exc


# ---------------------------------------------------------------------------
# OAuth / AGY
# ---------------------------------------------------------------------------

def token_expired(account: Account, safety_seconds: int = 60) -> bool:
    if not account.expires_at:
        return False

    value = str(account.expires_at)

    try:
        if value.isdigit():
            expiry = float(value)
        else:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            expiry = dt.timestamp()

        return time.time() + safety_seconds >= expiry

    except Exception:
        return False


def refresh_token(
    account: Account,
) -> None:
    if not account.refresh_token:
        raise GatewayError(
            f"{account.name} has no refresh token."
        )

    fields = {
        "grant_type": "refresh_token",
        "refresh_token": account.refresh_token,
    }

    client_id = os.getenv("AGY_CLIENT_ID")
    client_secret = os.getenv("AGY_CLIENT_SECRET")

    if client_id:
        fields["client_id"] = client_id

    if client_secret:
        fields["client_secret"] = client_secret

    request = Request(
        TOKEN_URL,
        data=urlencode(fields).encode("utf-8"),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": client_user_agent(account),
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=30) as response:
            data = json.loads(
                response.read().decode("utf-8", errors="replace")
            )

    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")

        if "invalid_grant" in raw:
            raise GatewayError(
                f"Refresh token for {account.name} is invalid/revoked."
            ) from exc

        raise GatewayError(
            f"OAuth refresh failed for {account.name}: "
            f"HTTP {exc.code} {raw[:3000]}"
        ) from exc

    except URLError as exc:
        raise GatewayError(
            f"OAuth refresh network error: {exc}"
        ) from exc

    access_token = data.get("access_token")

    if not isinstance(access_token, str) or not access_token:
        raise GatewayError(
            f"OAuth refresh returned no access_token for {account.name}."
        )

    account.access_token = access_token

    rotated_refresh = data.get("refresh_token")
    if isinstance(rotated_refresh, str) and rotated_refresh:
        account.refresh_token = rotated_refresh

    expires_in = data.get("expires_in")
    if isinstance(expires_in, (int, float)):
        account.expires_at = str(
            int(time.time() + int(expires_in))
        )


# ---------------------------------------------------------------------------
# Quota/cooldown
# ---------------------------------------------------------------------------

def cooldown_remaining(account: Account) -> int:
    value = account.extra.get("_rate_limit_until")

    if value is None:
        return 0

    try:
        return max(0, int(float(value) - time.time()))
    except Exception:
        return 0


def account_available(account: Account) -> bool:
    return cooldown_remaining(account) <= 0


def set_cooldown(
    account: Account,
    seconds: Optional[int],
    reason: str,
    default_seconds: int,
) -> None:
    duration = int(seconds or default_seconds)
    duration = max(2, min(duration, 86400))

    account.extra["_rate_limit_until"] = time.time() + duration
    account.extra["_rate_limit_reason"] = reason[:1000]


def is_retryable_account_error(exc: Exception) -> bool:
    if isinstance(exc, UpstreamHTTPError):
        if exc.status in {429, 500, 502, 503, 504}:
            return True

    message = str(exc).lower()

    retry_words = (
        "rate limit",
        "rate-limit",
        "too many requests",
        "quota exceeded",
        "quota exhausted",
        "resource exhausted",
        "capacity",
        "high traffic",
        "temporarily unavailable",
        "service unavailable",
        "resets after",
        "resets in",
        "retry after",
    )

    return any(word in message for word in retry_words)


# ---------------------------------------------------------------------------
# Antigravity request logic
# ---------------------------------------------------------------------------

class AntigravityClient:
    def __init__(self, account: Account, config: Dict[str, Any]):
        self.account = account
        self.config = config

    def save(self) -> None:
        store = AccountStore()

        if self.account.name in store.accounts:
            store.accounts[self.account.name] = self.account
            store.save()

    def ensure_access_token(self) -> None:
        if not self.account.access_token:
            refresh_token(self.account)
            self.save()
            return

        if token_expired(self.account):
            refresh_token(self.account)
            self.save()

    def discover_project(self, force: bool = False) -> str:
        if self.account.project_id and not force:
            return self.account.project_id

        self.ensure_access_token()

        headers = content_headers(self.account)
        body = {
            "metadata": {
                "ideType": "ANTIGRAVITY"
            }
        }

        last_error: Optional[Exception] = None

        for base in BOOTSTRAP_BASE_URLS:
            try:
                data = request_json(
                    f"{base}{LOAD_CODE_ASSIST_PATH}",
                    method="POST",
                    headers=headers,
                    body=body,
                    timeout=8,
                )
            except Exception as exc:
                last_error = exc
                continue

            project = data.get("cloudaicompanionProject")

            if isinstance(project, str):
                project_id = project.strip()
            elif isinstance(project, dict):
                project_id = str(
                    project.get("id") or ""
                ).strip()
            else:
                project_id = ""

            if project_id:
                self.account.project_id = project_id
                self.save()
                return project_id

        if last_error:
            raise last_error

        raise GatewayError(
            f"No projectId returned for {self.account.email or self.account.name}."
        )

    def list_models(self) -> List[Dict[str, Any]]:
        self.ensure_access_token()

        headers = content_headers(self.account)
        body = {
            "metadata": {
                "ideType": "ANTIGRAVITY"
            }
        }

        for base in (
            *RUNTIME_BASE_URLS,
            "https://daily-cloudcode-pa.sandbox.googleapis.com",
        ):
            try:
                data = request_json(
                    f"{base}{FETCH_AVAILABLE_MODELS_PATH}",
                    method="POST",
                    headers=headers,
                    body=body,
                    timeout=15,
                )

                models = extract_models(data)

                if models:
                    return models

            except Exception:
                continue

        return [
            {
                "id": model_id,
                "object": "model",
                "owned_by": "antigravity",
            }
            for model_id in PUBLIC_MODELS
        ]

    def generate(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        custom_instruction: str,
        temperature: Optional[float],
        max_output_tokens: int,
    ) -> Dict[str, Any]:
        self.ensure_access_token()

        project_id = self.discover_project()

        contents = normalize_messages(
            messages,
            custom_instruction,
        )

        request_body: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": min(
                    int(max_output_tokens),
                    16384,
                ),
                "topK": 40,
                "topP": 1.0,
            },
            "sessionId": generate_session_id(),
        }

        if temperature is not None:
            request_body["generationConfig"]["temperature"] = float(
                temperature
            )

        envelope = {
            "project": project_id,
            "requestId": str(uuid.uuid4()),
            "request": request_body,
            "model": model.split("/")[-1],
            "userAgent": "antigravity",
            "requestType": "agent",
        }

        return self._request(envelope, model)

    def stream(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        custom_instruction: str,
        temperature: Optional[float],
        max_output_tokens: int,
    ) -> Iterator[str]:
        self.ensure_access_token()

        project_id = self.discover_project()

        contents = normalize_messages(
            messages,
            custom_instruction,
        )

        request_body: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": min(
                    int(max_output_tokens),
                    16384,
                ),
                "topK": 40,
                "topP": 1.0,
            },
            "sessionId": generate_session_id(),
        }

        if temperature is not None:
            request_body["generationConfig"]["temperature"] = float(
                temperature
            )

        envelope = {
            "project": project_id,
            "requestId": str(uuid.uuid4()),
            "request": request_body,
            "model": model.split("/")[-1],
            "userAgent": "antigravity",
            "requestType": "agent",
        }

        yield from self._stream(envelope)

    def _request(
        self,
        envelope: Dict[str, Any],
        model: str,
    ) -> Dict[str, Any]:
        last_error: Optional[Exception] = None

        timeout = int(
            self.config.get(
                "request_timeout_seconds",
                600,
            )
        )

        for base in RUNTIME_BASE_URLS:
            request = Request(
                f"{base}{STREAM_GENERATE_PATH}",
                data=json.dumps(envelope).encode("utf-8"),
                headers={
                    **content_headers(self.account),
                    "Accept": "text/event-stream",
                },
                method="POST",
            )

            try:
                with urlopen(request, timeout=timeout) as response:
                    raw = response.read().decode(
                        "utf-8",
                        errors="replace",
                    )
                    return parse_sse_response(raw, model)

            except HTTPError as exc:
                raw = exc.read().decode(
                    "utf-8",
                    errors="replace",
                )

                retry_after = parse_retry_after_seconds(
                    exc.headers.get("Retry-After")
                )

                if retry_after is None:
                    retry_after = extract_retry_seconds(raw)

                last_error = UpstreamHTTPError(
                    exc.code,
                    f"HTTP {exc.code} from Antigravity: {raw[:5000]}",
                    retry_after,
                )

                if exc.code in {429, 500, 502, 503, 504}:
                    continue

                raise last_error

            except URLError as exc:
                last_error = GatewayError(
                    f"Antigravity network error: {exc}"
                )

        if last_error:
            raise last_error

        raise GatewayError("Antigravity request failed.")

    def _stream(
        self,
        envelope: Dict[str, Any],
    ) -> Iterator[str]:
        timeout = int(
            self.config.get(
                "request_timeout_seconds",
                600,
            )
        )

        for base in RUNTIME_BASE_URLS:
            request = Request(
                f"{base}{STREAM_GENERATE_PATH}",
                data=json.dumps(envelope).encode("utf-8"),
                headers={
                    **content_headers(self.account),
                    "Accept": "text/event-stream",
                },
                method="POST",
            )

            try:
                with urlopen(request, timeout=timeout) as response:
                    for raw_line in response:
                        line = raw_line.decode(
                            "utf-8",
                            errors="replace",
                        ).strip()

                        if not line.startswith("data:"):
                            continue

                        payload = line[5:].strip()

                        if payload == "[DONE]":
                            return

                        try:
                            event = json.loads(payload)
                        except json.JSONDecodeError:
                            continue

                        text = extract_sse_text(event)

                        if text:
                            yield text

                return

            except HTTPError as exc:
                raw = exc.read().decode(
                    "utf-8",
                    errors="replace",
                )

                retry_after = parse_retry_after_seconds(
                    exc.headers.get("Retry-After")
                )

                if retry_after is None:
                    retry_after = extract_retry_seconds(raw)

                if exc.code in {429, 500, 502, 503, 504}:
                    raise UpstreamHTTPError(
                        exc.code,
                        f"HTTP {exc.code} from Antigravity: {raw[:5000]}",
                        retry_after,
                    ) from exc

                raise UpstreamHTTPError(
                    exc.code,
                    f"HTTP {exc.code}: {raw[:5000]}",
                    retry_after,
                ) from exc

            except URLError as exc:
                raise GatewayError(
                    f"Antigravity network error: {exc}"
                ) from exc

        raise GatewayError(
            "All Antigravity runtime endpoints failed."
        )


# ---------------------------------------------------------------------------
# Message conversion / instruction
# ---------------------------------------------------------------------------

def normalize_messages(
    messages: List[Dict[str, Any]],
    custom_instruction: str,
) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []

    instruction = custom_instruction.strip()

    if instruction:
        result.append(
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            "Follow this instruction throughout the conversation:\n\n"
                            + instruction
                        )
                    }
                ],
            }
        )

    for message in messages:
        role = str(message.get("role") or "user")
        content = message.get("content", "")

        if role == "system":
            # Put system instructions into the same instruction block.
            text = content_to_text(content)

            if text:
                if result and result[0]["role"] == "user":
                    result[0]["parts"][0]["text"] += (
                        "\n\nAdditional system instruction:\n\n" + text
                    )
                else:
                    result.insert(
                        0,
                        {
                            "role": "user",
                            "parts": [{"text": text}],
                        },
                    )

            continue

        if role == "assistant":
            role = "model"

        elif role not in {"user", "model"}:
            role = "user"

        text = content_to_text(content)

        if not text:
            continue

        result.append(
            {
                "role": role,
                "parts": [{"text": text}],
            }
        )

    if not result:
        result = [
            {
                "role": "user",
                "parts": [{"text": "Hello"}],
            }
        ]

    return merge_adjacent_contents(result)


def content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: List[str] = []

        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") in {"text", "input_text"}:
                    value = item.get("text")
                    if isinstance(value, str):
                        parts.append(value)

        return "\n".join(parts)

    if isinstance(content, dict):
        value = content.get("text")
        if isinstance(value, str):
            return value

    return str(content) if content is not None else ""


def merge_adjacent_contents(
    contents: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []

    for current in contents:
        if (
            merged
            and merged[-1]["role"] == current["role"]
        ):
            merged[-1]["parts"].extend(
                current.get("parts", [])
            )
        else:
            merged.append(current)

    return merged


# ---------------------------------------------------------------------------
# SSE parsing / OpenAI response
# ---------------------------------------------------------------------------

def extract_sse_text(data: Any) -> str:
    if not isinstance(data, dict):
        return ""

    direct = data.get("text")
    if isinstance(direct, str):
        return direct

    candidates = data.get("candidates")

    if not isinstance(candidates, list):
        return ""

    pieces: List[str] = []

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue

        content = candidate.get("content")

        if not isinstance(content, dict):
            continue

        parts = content.get("parts")

        if not isinstance(parts, list):
            continue

        for part in parts:
            if not isinstance(part, dict):
                continue

            text = part.get("text")

            if isinstance(text, str):
                pieces.append(text)

    return "".join(pieces)


def parse_sse_response(
    raw: str,
    model: str,
) -> Dict[str, Any]:
    pieces: List[str] = []
    raw_events: List[Dict[str, Any]] = []

    for line in raw.splitlines():
        line = line.strip()

        if not line.startswith("data:"):
            continue

        payload = line[5:].strip()

        if payload == "[DONE]":
            continue

        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue

        raw_events.append(event)

        text = extract_sse_text(event)

        if text:
            pieces.append(text)

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "".join(pieces),
                },
                "finish_reason": "stop",
            }
        ],
        "events": raw_events,
    }


def make_openai_models(models: List[Dict[str, Any]]) -> Dict[str, Any]:
    data: List[Dict[str, Any]] = []

    seen = set()

    for item in models:
        model_id = item.get("id")

        if not isinstance(model_id, str):
            continue

        if model_id in seen:
            continue

        seen.add(model_id)

        data.append(
            {
                "id": model_id,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "antigravity",
            }
        )

    return {
        "object": "list",
        "data": data,
    }


def generate_session_id() -> str:
    value = int(uuid.uuid4().hex[:8], 16)
    value %= 9_000_000_000_000_000_000
    return f"-{value}"


# ---------------------------------------------------------------------------
# Account fallback
# ---------------------------------------------------------------------------

def available_accounts(
    store: AccountStore,
    current_first: bool = True,
) -> List[Account]:
    current_name = store.current_name()
    accounts = list(store.accounts.values())

    if current_first and current_name in store.accounts:
        current = store.accounts[current_name]
        accounts = [
            current,
            *[
                a for a in accounts
                if a.name != current_name
            ],
        ]

    return [
        account
        for account in accounts
        if account_available(account)
    ]


def generate_with_fallback(
    *,
    store: AccountStore,
    config: Dict[str, Any],
    model: str,
    messages: List[Dict[str, Any]],
    custom_instruction: str,
    temperature: Optional[float],
    max_output_tokens: int,
) -> Dict[str, Any]:
    accounts = available_accounts(store)

    if not accounts:
        raise GatewayError(
            "No account is currently available. "
            "All configured accounts are in cooldown."
        )

    max_attempts = int(
        config.get("max_account_attempts", 0) or 0
    )

    if max_attempts > 0:
        accounts = accounts[:max_attempts]

    last_error: Optional[Exception] = None

    for account in accounts:
        client = AntigravityClient(account, config)

        try:
            result = client.generate(
                model=model,
                messages=messages,
                custom_instruction=custom_instruction,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )

            # Successful account becomes the selected account.
            clear = account.extra.pop("_rate_limit_until", None)
            account.extra.pop("_rate_limit_reason", None)
            store.accounts[account.name] = account
            store.save()

            if store.current_name() != account.name:
                store.set_current(account.name)

            return result

        except Exception as exc:
            last_error = exc

            if not is_retryable_account_error(exc):
                # Retry another account only for authentication failures.
                text = str(exc).lower()

                auth_failure = (
                    "http 401" in text
                    or "http 403" in text
                    or "invalid_grant" in text
                    or "unauthorized" in text
                    or "token" in text and "invalid" in text
                )

                if not auth_failure:
                    raise

            retry_after = (
                exc.retry_after
                if isinstance(exc, UpstreamHTTPError)
                else None
            )

            if retry_after is None:
                retry_after = extract_retry_seconds(str(exc))

            set_cooldown(
                account,
                retry_after,
                str(exc),
                int(config.get("cooldown_default_seconds", 60)),
            )

            store.accounts[account.name] = account
            store.save()

    if last_error:
        raise GatewayError(
            f"All available Antigravity accounts failed.\n"
            f"Last error: {last_error}"
        ) from last_error

    raise GatewayError("No account succeeded.")


def stream_with_fallback(
    *,
    store: AccountStore,
    config: Dict[str, Any],
    model: str,
    messages: List[Dict[str, Any]],
    custom_instruction: str,
    temperature: Optional[float],
    max_output_tokens: int,
) -> Iterator[tuple[str, str]]:
    """
    Yields:
      ("chunk", text)
      ("done", account_name)

    A quota error that occurs before streaming content reaches the client
    causes account rotation. Once content has been sent to the client,
    a mid-stream failure cannot safely replay the partial response.
    """

    accounts = available_accounts(store)

    if not accounts:
        raise GatewayError(
            "No account is currently available."
        )

    max_attempts = int(
        config.get("max_account_attempts", 0) or 0
    )

    if max_attempts > 0:
        accounts = accounts[:max_attempts]

    for account in accounts:
        client = AntigravityClient(account, config)
        yielded_any = False

        try:
            iterator = client.stream(
                model=model,
                messages=messages,
                custom_instruction=custom_instruction,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )

            for chunk in iterator:
                yielded_any = True
                yield ("chunk", chunk)

            account.extra.pop("_rate_limit_until", None)
            account.extra.pop("_rate_limit_reason", None)
            store.accounts[account.name] = account
            store.save()

            if store.current_name() != account.name:
                store.set_current(account.name)

            yield ("done", account.name)
            return

        except Exception as exc:
            if yielded_any:
                # Partial output already reached the client. Do not replay.
                raise

            if not is_retryable_account_error(exc):
                text = str(exc).lower()

                auth_failure = (
                    "http 401" in text
                    or "http 403" in text
                    or "invalid_grant" in text
                    or "unauthorized" in text
                )

                if not auth_failure:
                    raise

            retry_after = (
                exc.retry_after
                if isinstance(exc, UpstreamHTTPError)
                else extract_retry_seconds(str(exc))
            )

            set_cooldown(
                account,
                retry_after,
                str(exc),
                int(config.get("cooldown_default_seconds", 60)),
            )

            store.accounts[account.name] = account
            store.save()

    raise GatewayError(
        "All available Antigravity accounts failed before streaming."
    )


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

class GatewayHandler(BaseHTTPRequestHandler):
    server_version = "AntigravityGateway/1.0"

    def _config(self) -> Dict[str, Any]:
        return self.server.gateway_config

    def _authorized(self) -> bool:
        configured = str(self._config().get("api_key") or "")

        if not configured:
            return True

        provided = self.headers.get("Authorization", "")

        if provided.startswith("Bearer "):
            return provided[7:].strip() == configured

        return self.headers.get("X-API-Key", "") == configured

    def _json_response(
        self,
        payload: Dict[str, Any],
        status: int = 200,
    ) -> None:
        body = json.dumps(
            payload,
            ensure_ascii=False,
        ).encode("utf-8")

        self.send_response(status)
        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8",
        )
        self.send_header(
            "Content-Length",
            str(len(body)),
        )
        self.send_header(
            "Cache-Control",
            "no-store",
        )
        self.end_headers()
        self.wfile.write(body)

    def _error(
        self,
        message: str,
        status: int = 500,
        error_type: str = "server_error",
    ) -> None:
        self._json_response(
            {
                "error": {
                    "message": message,
                    "type": error_type,
                }
            },
            status,
        )

    def _read_json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")

        if length <= 0:
            return {}

        raw = self.rfile.read(length)

        try:
            data = json.loads(
                raw.decode("utf-8")
            )
        except json.JSONDecodeError as exc:
            raise GatewayError(
                f"Invalid JSON request: {exc}"
            ) from exc

        if not isinstance(data, dict):
            raise GatewayError(
                "JSON request body must be an object."
            )

        return data

    def do_GET(self) -> None:
        try:
            if self.path == "/health":
                self._json_response(
                    {
                        "status": "ok",
                        "service": "antigravity-gateway",
                        "accounts": len(
                            AccountStore().accounts
                        ),
                    }
                )
                return

            if self.path in {"/v1/models", "/models"}:
                if not self._authorized():
                    self._error(
                        "Unauthorized",
                        401,
                        "authentication_error",
                    )
                    return

                store = AccountStore()
                account = store.current()
                client = AntigravityClient(
                    account,
                    self._config(),
                )

                models = client.list_models()

                self._json_response(
                    make_openai_models(models)
                )
                return

            if self.path in {"/", "/v1"}:
                self._json_response(
                    {
                        "name": "antigravity-gateway",
                        "version": "1.0",
                        "openai_compatible": True,
                        "endpoints": [
                            "/v1/models",
                            "/v1/chat/completions",
                        ],
                    }
                )
                return

            self._error(
                "Not found",
                404,
                "not_found",
            )

        except Exception as exc:
            self._error(str(exc), 500)

    def do_POST(self) -> None:
        try:
            if not self._authorized():
                self._error(
                    "Unauthorized",
                    401,
                    "authentication_error",
                )
                return

            if self.path not in {
                "/v1/chat/completions",
                "/chat/completions",
            }:
                self._error(
                    "Not found",
                    404,
                    "not_found",
                )
                return

            body = self._read_json_body()

            model = str(
                body.get("model")
                or "gemini-3.6-flash-high"
            )

            messages = body.get("messages")

            if not isinstance(messages, list):
                raise GatewayError(
                    "`messages` must be an array."
                )

            config = self._config()

            # Custom instruction precedence:
            # 1. request.custom_instruction
            # 2. request.system_instruction
            # 3. system messages inside messages
            # 4. gateway_config.json custom_instruction
            custom_instruction = str(
                body.get("custom_instruction")
                or body.get("system_instruction")
                or config.get("custom_instruction")
                or ""
            )

            temperature = body.get("temperature")

            if temperature is not None:
                temperature = float(temperature)

            max_output_tokens = int(
                body.get(
                    "max_tokens",
                    body.get(
                        "max_output_tokens",
                        config.get(
                            "max_output_tokens",
                            8192,
                        ),
                    ),
                )
            )

            stream = bool(
                body.get("stream", False)
            )

            store = AccountStore()

            if stream:
                self._handle_streaming(
                    store=store,
                    config=config,
                    model=model,
                    messages=messages,
                    custom_instruction=custom_instruction,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                )
                return

            result = generate_with_fallback(
                store=store,
                config=config,
                model=model,
                messages=messages,
                custom_instruction=custom_instruction,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )

            self._json_response(
                result,
                200,
            )

        except UpstreamHTTPError as exc:
            status = (
                exc.status
                if exc.status in {400, 401, 403, 404, 409, 422, 429}
                else 502
            )

            self._error(
                str(exc),
                status,
                "upstream_error",
            )

        except GatewayError as exc:
            self._error(
                str(exc),
                500,
                "gateway_error",
            )

        except Exception as exc:
            self._error(
                str(exc),
                500,
                "server_error",
            )

    def _handle_streaming(
        self,
        *,
        store: AccountStore,
        config: Dict[str, Any],
        model: str,
        messages: List[Dict[str, Any]],
        custom_instruction: str,
        temperature: Optional[float],
        max_output_tokens: int,
    ) -> None:
        self.send_response(200)
        self.send_header(
            "Content-Type",
            "text/event-stream; charset=utf-8",
        )
        self.send_header(
            "Cache-Control",
            "no-cache",
        )
        self.send_header(
            "Connection",
            "keep-alive",
        )
        self.end_headers()

        completion_id = (
            f"chatcmpl-{uuid.uuid4().hex}"
        )
        created = int(time.time())

        try:
            for kind, value in stream_with_fallback(
                store=store,
                config=config,
                model=model,
                messages=messages,
                custom_instruction=custom_instruction,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            ):
                if kind == "chunk":
                    payload = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "role": "assistant",
                                    "content": value,
                                },
                                "finish_reason": None,
                            }
                        ],
                    }

                    self._send_sse(payload)

                elif kind == "done":
                    payload = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {},
                                "finish_reason": "stop",
                            }
                        ],
                    }

                    self._send_sse(payload)
                    self._send_sse_raw("[DONE]")

        except Exception as exc:
            # At this point some stream data may already have reached the
            # client, so send a terminal SSE error rather than changing
            # response headers/status.
            self._send_sse(
                {
                    "error": {
                        "message": str(exc),
                        "type": "upstream_error",
                    }
                }
            )
            self._send_sse_raw("[DONE]")

    def _send_sse(
        self,
        payload: Dict[str, Any],
    ) -> None:
        self._send_sse_raw(
            json.dumps(
                payload,
                ensure_ascii=False,
            )
        )

    def _send_sse_raw(self, payload: str) -> None:
        data = f"data: {payload}\n\n".encode(
            "utf-8"
        )
        self.wfile.write(data)
        self.wfile.flush()

    def log_message(
        self,
        format_string: str,
        *args: Any,
    ) -> None:
        sys.stderr.write(
            "[gateway] "
            + format_string % args
            + "\n"
        )


class GatewayServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address,
        handler_class,
        gateway_config,
    ):
        self.gateway_config = gateway_config
        super().__init__(
            server_address,
            handler_class,
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def check_files() -> None:
    if not ACCOUNTS_FILE.exists():
        sample = {
            "accounts": [
                {
                    "name": "account1",
                    "email": "your-account@gmail.com",
                    "access_token": "PASTE_ACCESS_TOKEN",
                    "refresh_token": "PASTE_REFRESH_TOKEN",
                    "expires_at": None,
                    "project_id": None,
                }
            ]
        }

        write_json(
            ACCOUNTS_FILE,
            sample,
        )

        print(
            f"Created example {ACCOUNTS_FILE}. "
            "Fill it with your OAuth credentials first.",
            file=sys.stderr,
        )


def main() -> int:
    check_files()

    config = ensure_config_file()

    # Load once at startup to fail early if malformed.
    store = AccountStore()

    if not store.accounts:
        print(
            f"No accounts configured in {ACCOUNTS_FILE}.",
            file=sys.stderr,
        )
        return 1

    host = str(
        config.get("host", "127.0.0.1")
    )

    port = int(
        config.get("port", 8000)
    )

    server = GatewayServer(
        (host, port),
        GatewayHandler,
        config,
    )

    print()
    print("=" * 64)
    print(" Antigravity Multi-Account Gateway")
    print("=" * 64)
    print(f" API:       http://{host}:{port}/v1")
    print(f" Models:    http://{host}:{port}/v1/models")
    print(f" Health:    http://{host}:{port}/health")
    print(f" Accounts:  {len(store.accounts)}")
    print(
        f" Active:    {store.current().name}"
        f" ({store.current().email})"
    )
    print(
        " Fallback:  automatic on quota/rate-limit/capacity"
    )
    print(
        " Instruction:",
        "configured" if config.get("custom_instruction") else "none",
    )
    print("=" * 64)
    print()
    print("Press Ctrl+C to stop.")

    try:
        server.serve_forever()

    except KeyboardInterrupt:
        print("\nStopping gateway...")

    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())