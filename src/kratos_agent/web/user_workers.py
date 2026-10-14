"""Independent worker processes for concurrent browser workspace profiles."""
from __future__ import annotations

import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import requests


class UserWorkerError(RuntimeError):
    pass


def validate_profile(value: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ValueError("Invalid user workspace profile")
    return value


@dataclass
class UserWorker:
    process: subprocess.Popen
    port: int
    token: str
    workspace: Path
    started_at: float
    ready: bool = False


class UserWorkerPool:
    def __init__(self, workspace: Path, *, max_users: int = 4):
        self.workspace = workspace.resolve()
        self.directory = self.workspace / ".kratos" / "users"
        self.max_users = max(2, min(32, max_users))
        self._lock = threading.Lock()
        self._workers: dict[str, UserWorker] = {}
        self._owner: str | None = None
        self._closed = False
        try:
            self._owner = validate_profile(json.loads((self.directory / "owner.json").read_text())['profile'])
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def route(self, profile: str) -> UserWorker | None:
        profile = validate_profile(profile)
        with self._lock:
            if self._closed:
                raise UserWorkerError("Studio is shutting down")
            # The first browser retains the original workspace and saved sessions.
            if self._owner is None:
                self.directory.mkdir(parents=True, exist_ok=True)
                path = self.directory / "owner.json"
                temporary = path.with_suffix('.tmp')
                temporary.write_text(json.dumps({'profile': profile}), encoding='utf-8')
                temporary.replace(path)
                self._owner = profile
            if profile == self._owner:
                return None
            worker = self._workers.get(profile)
            if worker and worker.process.poll() is not None:
                # Preserve its files and history, while replacing a crashed process.
                del self._workers[profile]
                worker = None
            if worker is None:
                if len(self._workers) >= self.max_users - 1:
                    raise UserWorkerError(f"The {self.max_users} user worker limit is reached. Increase KRATOS_MAX_USERS or restart Studio to release idle workers.")
                worker = self._start(profile)
                self._workers[profile] = worker
            return worker

    def _start(self, profile: str) -> UserWorker:
        directory = self.directory / profile
        workspace = directory / 'workspace'
        workspace.mkdir(parents=True, exist_ok=True)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        token = secrets.token_urlsafe(32)
        environment = os.environ.copy()
        environment.update({
            'KRATOS_PROFILE_WORKER_ID': profile, 'KRATOS_INTERNAL_TOKEN': token,
            'KRATOS_STRICT_PORT': '1', 'KRATOS_DISABLE_LIVE': '1',
            # User records stay in the profile's local database. A shared cloud
            # database must not expose another profile through unscoped queries.
            'CLOUDFLARE_ACCOUNT_ID': '', 'CLOUDFLARE_D1_DATABASE_ID': '', 'CLOUDFLARE_API_TOKEN': '',
            'KRATOS_COMPUTER_USE_MCP': '0', 'KRATOS_OPENPETS_MCP': '0',
            'KRATOS_GITNEXUS_MCP': '0', 'KRATOS_COMPOSIO_MCP': '0',
            'KRATOS_CONTEXT7_MCP': '0',
        })
        # Shared desktop/account integrations are opted into per workspace.
        # A new user's first request must not open the owner's mail or microphone.
        config_dir = workspace / '.kratos'
        config_dir.mkdir(exist_ok=True)
        mcp = config_dir / 'mcp.json'
        if not mcp.exists():
            mcp.write_text(json.dumps({'mcpServers': {}, 'imports': []}), encoding='utf-8')
        command = [sys.executable, '-m', 'kratos_agent.web.server', '--port', str(port), '--no-browser']
        with (directory / 'worker.log').open('ab') as output:
            process = subprocess.Popen(command, cwd=workspace, env=environment, stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        return UserWorker(process, port, token, workspace, time.monotonic())

    @staticmethod
    def is_ready(worker: UserWorker) -> bool:
        if worker.process.poll() is not None:
            raise UserWorkerError('User worker stopped. Refresh to resume its saved workspace.')
        if worker.ready:
            return True
        http = requests.Session()
        http.trust_env = False
        try:
            response = http.get(f'http://127.0.0.1:{worker.port}/api/health',
                                headers={'X-Kratos-Internal-Token': worker.token}, timeout=.5)
            worker.ready = response.ok and response.json().get('service') == 'kratos'
        except (requests.RequestException, ValueError):
            pass
        finally:
            http.close()
        return worker.ready

    def close(self) -> None:
        with self._lock:
            self._closed = True
            workers = list(self._workers.values())
            self._workers.clear()
        import psutil
        for worker in workers:
            try:
                parent = psutil.Process(worker.process.pid)
                owned = parent.children(recursive=True)
                for process in reversed(owned):
                    try:
                        process.terminate()
                    except psutil.NoSuchProcess:
                        pass
                parent.terminate()
                _, alive = psutil.wait_procs([parent, *owned], timeout=3)
                for process in alive:
                    try:
                        process.kill()
                    except psutil.NoSuchProcess:
                        pass
            except psutil.NoSuchProcess:
                pass
