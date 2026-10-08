"""Docker is healthy only after both supervised services answer correctly."""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import psutil


def internal_token() -> str:
    # Inspect only the owned agent process in this container's PID namespace.
    # Studio creates a new token on each launch and keeps it out of disk files.
    for process in psutil.process_iter(["cmdline"]):
        if "kratos_agent.web.server" not in (process.info["cmdline"] or []):
            continue
        try:
            token = process.environ().get("KRATOS_INTERNAL_TOKEN", "")
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
        if token:
            return token
    raise RuntimeError("Agent process is not initialized")


def check(workspace: Path = Path("/workspace")) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    gateway_port = int(os.environ.get("KRATOS_PORT", "21128"))
    agent_port = int(os.environ.get("KRATOS_AGENT_PORT", "7860"))
    secrets_file = workspace / ".kratos/studio/gateway/studio-secrets.json"
    saved = json.loads(secrets_file.read_text(encoding="utf-8"))
    if not saved.get("KRATOS_GATEWAY_API_KEY"):
        raise RuntimeError("Gateway API credential has not been initialized")
    with opener.open(f"http://127.0.0.1:{gateway_port}/api/health", timeout=3) as response:
        if response.status != 200:
            raise RuntimeError("Gateway is not ready")
    request = urllib.request.Request(
        f"http://127.0.0.1:{agent_port}/api/health",
        headers={"X-Kratos-Internal-Token": internal_token()},
    )
    with opener.open(request, timeout=3) as response:
        if response.status != 200:
            raise RuntimeError("Agent is not ready")


if __name__ == "__main__":
    try:
        check()
    except Exception as exc:
        print(f"Kratos not ready: {exc}", file=sys.stderr)
        sys.exit(1)
