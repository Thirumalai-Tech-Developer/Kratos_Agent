from __future__ import annotations

import json
import os
import re
import sys
import time
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# Candidate locations for accounts.json
POSSIBLE_ACCOUNT_PATHS = [
    Path(os.environ.get("KRATOS_ACCOUNTS_FILE", "")) if os.environ.get("KRATOS_ACCOUNTS_FILE") else Path.cwd() / "accounts.json",
    Path.cwd() / "accounts.json",
    Path.home() / ".config" / "antigravity" / "accounts.json",
    Path.home() / ".antigravity" / "accounts.json",
    Path(__file__).resolve().parent.parent.parent.parent / "accounts.json",
]

TOKEN_URL = "https://oauth2.googleapis.com/token"
BOOTSTRAP_BASE_URLS = [
    "https://cloudcode-pa.googleapis.com",
]
LOAD_CODE_ASSIST_PATH = "/v1internal:loadCodeAssist"

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

class AntigravityAuthError(RuntimeError):
    pass

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
    id: str = ""
    provider: str = "agy"
    
    # Internal cooldown tracking
    _rate_limit_until: float = 0.0
    _rate_limit_reason: str = ""

    def is_rate_limited(self) -> bool:
        return time.time() < self._rate_limit_until

    def mark_rate_limited(self, duration_seconds: float = 60.0, reason: str = "") -> None:
        self._rate_limit_until = time.time() + duration_seconds
        self._rate_limit_reason = reason

    def clear_rate_limit(self) -> None:
        self._rate_limit_until = 0.0
        self._rate_limit_reason = ""

    def is_token_expired(self, safety_seconds: int = 60) -> bool:
        return token_is_expired(self, safety_seconds=safety_seconds)

    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Account":
        known = {
            "name", "email", "access_token", "refresh_token",
            "expires_at", "project_id", "token_type", "auth_method", "client_profile"
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
            extra={k: v for k, v in data.items() if k not in known}
        )

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        extra = data.pop("extra", {})
        data.update(extra)
        return data

def get_agy_version() -> str:
    try:
        res = subprocess.run(["agy", "--version"], capture_output=True, text=True, timeout=1)
        if res.returncode == 0:
            m = re.search(r"(\d+\.\d+\.\d+)", res.stdout)
            if m:
                return m.group(1)
    except Exception:
        pass
    return "1.1.0"

def client_user_agent(account: Account) -> str:
    version = get_agy_version()
    return f"Antigravity/{version} darwin/arm64 ({account.client_profile})"

def content_headers(account: Account) -> Dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": client_user_agent(account),
        "X-Goog-Api-Client": "gl-python/3.14 gccl/antigravity",
    }
    if account.access_token:
        headers["Authorization"] = f"Bearer {account.access_token}"
    return headers

def token_is_expired(account: Account, safety_seconds: int = 120) -> bool:
    if not account.expires_at:
        return False
    raw = account.expires_at
    try:
        if str(raw).isdigit():
            expiry = float(raw)
        else:
            text = str(raw).replace("Z", "+00:00")
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            expiry = dt.timestamp()
        return (time.time() + safety_seconds) >= expiry
    except Exception:
        return False

DEFAULT_CLIENT_ID = os.environ.get("AGY_CLIENT_ID", "")
DEFAULT_CLIENT_SECRET = os.environ.get("AGY_CLIENT_SECRET", "")

def refresh_access_token(account: Account) -> bool:
    if not account.refresh_token:
        raise AntigravityAuthError(f"Account '{account.name}' has no refresh_token.")

    fields = {
        "grant_type": "refresh_token",
        "refresh_token": account.refresh_token,
        "client_id": DEFAULT_CLIENT_ID,
        "client_secret": DEFAULT_CLIENT_SECRET,
    }

    data = urlencode(fields).encode("utf-8")
    request = Request(
        TOKEN_URL,
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": client_user_agent(account),
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8", errors="replace"))
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            result = json.loads(raw)
        except Exception:
            result = {"error": raw}
        raise AntigravityAuthError(f"OAuth refresh failed (HTTP {exc.code}) for {account.name}: {raw[:500]}") from exc
    except URLError as exc:
        raise AntigravityAuthError(f"OAuth network error for {account.name}: {exc}") from exc

    access_token = result.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise AntigravityAuthError(f"OAuth refresh returned no access_token: {result}")

    account.access_token = access_token
    new_refresh = result.get("refresh_token")
    if isinstance(new_refresh, str) and new_refresh:
        account.refresh_token = new_refresh

    expires_in = result.get("expires_in")
    if isinstance(expires_in, (int, float)):
        account.expires_at = str(int(time.time() + int(expires_in)))

    return True

def discover_project(account: Account, force: bool = False) -> str:
    if account.project_id and not force:
        return account.project_id

    headers = content_headers(account)
    body = {"metadata": {"ideType": "ANTIGRAVITY"}}

    last_error = None
    for base in BOOTSTRAP_BASE_URLS:
        url = f"{base}{LOAD_CODE_ASSIST_PATH}"
        try:
            req = Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            with urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))

            cloudaicompanion_project = data.get("cloudaicompanionProject")
            if isinstance(cloudaicompanion_project, dict):
                pid = cloudaicompanion_project.get("id") or cloudaicompanion_project.get("projectId")
                if pid:
                    account.project_id = str(pid)
                    return account.project_id

            if isinstance(data.get("currentTier"), dict):
                pid = data["currentTier"].get("projectId")
                if pid:
                    account.project_id = str(pid)
                    return account.project_id

            if isinstance(data.get("project"), str) and data["project"]:
                account.project_id = data["project"]
                return account.project_id

        except HTTPError as exc:
            last_error = exc
            if exc.code == 401:
                refresh_access_token(account)
                headers = content_headers(account)
                continue
        except Exception as exc:
            last_error = exc

    if account.project_id:
        return account.project_id

    raise AntigravityAuthError(
        f"Could not discover project ID for account '{account.name}': {last_error}"
    )

class AccountStore:
    def __init__(self, file_path: Optional[Path] = None):
        self.file_path = file_path or self._find_accounts_file()
        self.accounts: Dict[str, Account] = {}
        self.load()

    def _find_accounts_file(self) -> Path:
        for p in POSSIBLE_ACCOUNT_PATHS:
            if p.exists() and p.is_file():
                return p
        return POSSIBLE_ACCOUNT_PATHS[0]

    def load(self) -> None:
        if not self.file_path or not self.file_path.exists():
            return
        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
            rows = data.get("accounts", []) if isinstance(data, dict) else data
            self.accounts = {}
            for r in rows:
                if isinstance(r, dict):
                    acc = Account.from_dict(r)
                    self.accounts[acc.name] = acc
        except Exception as e:
            print(f"[Warning] Failed loading accounts from {self.file_path}: {e}", file=sys.stderr)

    def save(self) -> None:
        if not self.file_path:
            return
        try:
            data = {"accounts": [a.to_dict() for a in self.accounts.values()]}
            self.file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

class AccountPool:
    """Manages multi-account load balancing, token refreshing, and cooldowns."""
    def __init__(self, store: Optional[AccountStore] = None):
        self.store = store or AccountStore()
        self.cooldowns: Dict[str, float] = {}
        self._current_index = 0

    @property
    def accounts(self) -> List[Account]:
        return list(self.store.accounts.values())

    def get_active_account(self) -> Optional[Account]:
        if not self.accounts:
            return None
        available = self.get_available_accounts()
        if not available:
            # If all are in cooldown, rotate through all accounts
            acc = self.accounts[self._current_index % len(self.accounts)]
            self._current_index = (self._current_index + 1) % len(self.accounts)
            return acc
        
        acc = available[self._current_index % len(available)]
        self._current_index = (self._current_index + 1) % len(available)
        return acc

    def get_available_accounts(self) -> List[Account]:
        now = time.time()
        return [
            a for a in self.accounts
            if self.cooldowns.get(a.name, 0) <= now
        ]

    def mark_cooldown(self, account_name: str, duration_seconds: float = 60.0):
        self.cooldowns[account_name] = time.time() + duration_seconds
        self._current_index = (self._current_index + 1) % max(1, len(self.accounts))

    def ensure_ready(self, account: Account) -> None:
        if not account.access_token or token_is_expired(account):
            refresh_access_token(account)
            self.store.save()

        if not account.project_id:
            discover_project(account)
            self.store.save()
