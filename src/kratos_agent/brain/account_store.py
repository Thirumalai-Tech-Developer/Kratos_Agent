"""User-level connection storage; account secrets never belong to a workspace."""

from __future__ import annotations

import ctypes
import json
import os
import tempfile
import uuid
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path

import portalocker


def account_directory() -> Path:
    if os.getenv('KRATOS_AUTH_DIR'):
        return Path(os.environ['KRATOS_AUTH_DIR'])
    if os.name == "nt":
        shared = Path.home() / '.kratos' / 'auth'
        if (shared / 'accounts.bin').is_file():
            return shared
        return (
            Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
            / "KratosAgent"
            / "auth"
        )
    return (
        Path(os.getenv("XDG_DATA_HOME") or Path.home() / ".local" / "share")
        / "kratos-agent"
        / "auth"
    )


def _windows_protect(data: bytes, *, decrypt: bool = False) -> bytes:
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    # CRYPTPROTECT_UI_FORBIDDEN; DPAPI binds this record to the Windows user.
    operation = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    operation.argtypes = [
        ctypes.POINTER(Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(Blob),
    ]
    operation.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not operation(
        ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)
    ):
        raise OSError("Windows could not protect the ChatGPT account record")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)


class AccountStore:
    def __init__(self, root: Path | None = None):
        self.root = (root or account_directory()).resolve()
        self.path = self.root / "accounts.bin"

    def promote_shared(self, target: Path | None = None) -> bool:
        """Preserve existing logins in a directory shared by MSIX and ordinary apps."""
        if target is None:
            legacy = Path(os.getenv('LOCALAPPDATA') or Path.home() / 'AppData/Local') / 'KratosAgent/auth'
            if os.name != 'nt' or os.getenv('KRATOS_AUTH_DIR') or self.root != legacy.resolve():
                return False
            target = Path.home() / '.kratos/auth'
        shared = AccountStore(target)
        if shared.root == self.root:
            return False
        with self.locked():
            state = self.read()
            # Do not promote a packaged application's empty shadow over a real login.
            if not state.get('web_accounts') and not state.get('accounts'):
                return False
            with shared.locked():
                if not shared.path.exists():
                    extension = self.root / 'browser-extension'
                    if (extension / 'config.js').is_file():
                        state['legacy_extension_directory'] = str(extension)
                    shared.write(state)
                else:
                    existing = shared.read()
                    if (existing.get('browser_bridge_token') != state.get('browser_bridge_token')
                            or existing.get('active_web_account') != state.get('active_web_account')):
                        raise RuntimeError('Shared browser storage already belongs to another connection')
        # Existing SDK and auth managers reference this same object.
        self.root, self.path = shared.root, shared.path
        return True

    @contextmanager
    def locked(self):
        """Serialize selection, token rotation and atomic writes across workers."""
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            self.root.chmod(0o700)
        with portalocker.Lock(self.root / "accounts.lock", mode="a+b", timeout=30):
            yield self

    def read(self) -> dict:
        if not self.path.exists():
            return {
                "host_id": "",
                "provider": "gateway",
                "active_account": "",
                "accounts": {},
            }
        try:
            data = self.path.read_bytes()
            if os.name == "nt":
                data = _windows_protect(data, decrypt=True)
            state = json.loads(data)
            if not isinstance(state, dict) or not isinstance(
                state.get("accounts"), dict
            ):
                raise TypeError("Invalid account record")
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeError(
                "ChatGPT account storage could not be read; credentials were not reset"
            ) from exc
        from kratos_agent.core.archive import register_sensitive_values

        register_sensitive_values(
            state.get("browser_bridge_token", ""),
            *(
                r.get(k, "")
                for r in state["accounts"].values()
                for k in ("access_token", "refresh_token", "id_token")
            ),
        )
        for record in state.get("web_accounts", {}).values():
            storage = record.get("storage_state", {})
            register_sensitive_values(
                *(cookie.get("value", "") for cookie in storage.get("cookies", [])),
                *(
                    value.get("value", "")
                    for origin in storage.get("origins", [])
                    for value in origin.get("localStorage", [])
                ),
            )
        return state

    def write(self, state: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        data = json.dumps(state, ensure_ascii=False).encode()
        if os.name == "nt":
            data = _windows_protect(data)
        fd, name = tempfile.mkstemp(prefix="accounts-", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            if os.name != "nt":
                os.chmod(name, 0o600)
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def host_id(self) -> str:
        with self.locked():
            state = self.read()
            if not state.get("host_id"):
                state["host_id"] = "urn:uuid:" + str(uuid.uuid4())
                self.write(state)
            return state["host_id"]

    def selected_model(self, provider: str | None = None) -> str:
        state = self.read()
        if (provider or state.get("provider")) in {"chatgpt-web", "browser-web"}:
            return str(
                state.get("web_accounts", {})
                .get(state.get("active_web_account"), {})
                .get("model", "")
            )
        return str(
            state["accounts"].get(state.get("active_account"), {}).get("model", "")
        )


account_store = AccountStore()
