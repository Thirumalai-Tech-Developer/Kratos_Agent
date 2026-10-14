"""Run the bundled Kratos workspace and OmniRoute application as one product."""
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
GATEWAY = ROOT / "services" / "omniroute"


def port_available(port: int) -> bool:
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def http_ready(url: str, token: str = "") -> bool:
    try:
        request = urllib.request.Request(url, headers={"X-Kratos-Internal-Token": token})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=2) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


class ManagedService:
    """Own only the process tree started by this supervisor."""

    def __init__(self, name: str, command: list[str], cwd: Path, env: dict[str, str], log: Path):
        self.name, self.command, self.cwd, self.env, self.log = name, command, cwd, env, log
        self.process: subprocess.Popen | None = None
        self.restarts = 0
        self._output = None

    def start(self) -> None:
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self._output = self.log.open("ab")
        try:
            self.process = subprocess.Popen(
                self.command, cwd=self.cwd, env=self.env, stdin=subprocess.DEVNULL,
                stdout=self._output, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )
        except Exception:
            self._output.close()
            raise

    def stop(self) -> None:
        if self.process:
            import psutil
            try:
                parent = psutil.Process(self.process.pid)
                children = parent.children(recursive=True)
                for child in reversed(children):
                    try:
                        child.terminate()
                    except psutil.NoSuchProcess:
                        pass
                parent.terminate()
                _, alive = psutil.wait_procs([parent, *children], timeout=5)
                for process in alive:
                    try:
                        process.kill()
                    except psutil.NoSuchProcess:
                        pass
            except psutil.NoSuchProcess:
                pass
            self.process.wait(timeout=10)
        if self._output:
            self._output.close()

    def wait_ready(self, url: str, timeout: float, token: str = "") -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process is None or self.process.poll() is not None:
                raise RuntimeError(f"{self.name} exited before readiness; see {self.log}")
            if http_ready(url, token):
                return
            time.sleep(0.25)
        raise RuntimeError(f"{self.name} did not become ready; see {self.log}")


def prepare_environment(args: argparse.Namespace) -> dict[str, str]:
    """Use the same workspace, settings and private gateway store in both interfaces."""
    workspace = args.workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    # Kratos settings take precedence over bundled OmniRoute settings. The
    # gateway's current local .env supplies provider and API-key configuration.
    load_dotenv(workspace / ".env", override=False)
    load_dotenv(ROOT / ".env", override=False)
    load_dotenv(GATEWAY / ".env", override=False)
    env = dict(os.environ)
    from kratos_agent.core.model_selection import read_selected_connection
    selection = read_selected_connection(workspace)
    if selection:
        env["KRATOS_MODEL"] = selection["model"]
        env["KRATOS_RUNTIME_MODEL"] = selection["model"]
        env["KRATOS_MODEL_PROVIDER"] = selection["provider"]
        env["KRATOS_RUNTIME_ACCOUNT_ID"] = selection["account_id"]
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["KRATOS_INTERNAL_TOKEN"] = secrets.token_urlsafe(32)
    env["OMNIROUTE_INTERNAL_SERVICE_TOKEN"] = env["KRATOS_INTERNAL_TOKEN"]
    env["KRATOS_AGENT_PORT"] = str(args.agent_port)
    env["KRATOS_BASE_URL"] = f"http://127.0.0.1:{args.port}/v1"
    env["KRATOS_CHAT_ENDPOINT"] = env["KRATOS_BASE_URL"] + "/chat/completions"
    env["KRATOS_MODEL_ENDPOINT"] = env["KRATOS_BASE_URL"] + "/models"
    env["KRATOS_STUDIO"] = "1"
    env["KRATOS_STRICT_PORT"] = "1"
    env["KRATOS_GATEWAY_URL"] = f"http://127.0.0.1:{args.port}"
    env["PORT"] = str(args.port)
    env["HOSTNAME"] = "127.0.0.1"
    env["HOST"] = "127.0.0.1"
    env["DASHBOARD_PORT"] = str(args.port)
    env["API_PORT"] = str(args.port)
    env["NEXT_TELEMETRY_DISABLED"] = "1"
    data_dir = args.data_dir.resolve() if args.data_dir else workspace / ".kratos" / "studio" / "gateway"
    data_dir.mkdir(parents=True, exist_ok=True)
    env["DATA_DIR"] = str(data_dir)
    # The merged product starts with its own store. Existing OmniRoute data is
    # adopted only through an explicit backup/import workflow.
    secrets_path = data_dir / "studio-secrets.json"
    if not secrets_path.exists():
        try:
            descriptor = os.open(secrets_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump({"JWT_SECRET": secrets.token_urlsafe(48),
                           "STORAGE_ENCRYPTION_KEY": secrets.token_hex(32),
                           "INITIAL_PASSWORD": env.get("INITIAL_PASSWORD") or secrets.token_urlsafe(24)}, output)
        except FileExistsError:
            pass
    saved_secrets = json.loads(secrets_path.read_text(encoding="utf-8"))
    missing = {
        "JWT_SECRET": lambda: secrets.token_urlsafe(48),
        "STORAGE_ENCRYPTION_KEY": lambda: secrets.token_hex(32),
        "INITIAL_PASSWORD": lambda: secrets.token_urlsafe(24),
        "KRATOS_GATEWAY_API_KEY": lambda: "sk-kratos-" + secrets.token_urlsafe(48),
    }
    if any(not saved_secrets.get(name) for name in missing):
        for name, generate in missing.items():
            if not saved_secrets.get(name):
                saved_secrets[name] = generate()
        temporary = secrets_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(saved_secrets), encoding="utf-8")
        temporary.replace(secrets_path)
    for name in missing:
        # The private Studio file owns these values, including imported encryption
        # keys. A repository .env must never override an imported data store.
        env[name] = saved_secrets[name]
    # OmniRoute supports a deployment-time inference key. Keep the managed
    # credential private and stable across both CLI and web launches.
    gateway_key = env.get("OMNIROUTE_API_KEY") or env.get("ROUTER_API_KEY") or saved_secrets["KRATOS_GATEWAY_API_KEY"]
    env["OMNIROUTE_API_KEY"] = gateway_key
    if not env.get("KRATOS_API_KEY"):
        env["KRATOS_API_KEY"] = gateway_key
    env["KRATOS_WORKSPACE"] = str(workspace)
    return env


def gateway_service(args: argparse.Namespace, env: dict[str, str]) -> ManagedService:
    if not (GATEWAY / "node_modules" / "next").exists():
        raise RuntimeError("Bundled gateway dependencies are missing. Run kratos-studio setup first.")
    log_dir = args.workspace.resolve() / ".kratos" / "studio" / "logs"
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required by the bundled gateway")
    gateway_env = dict(env)
    if args.dev:
        # Keep dev's routing cache separate from the standalone production build.
        gateway_env.setdefault("NEXT_DIST_DIR", ".build/kratos-dev")
        gateway_command = [node, "scripts/dev/run-next.mjs", "dev"]
        gateway_cwd = GATEWAY
    else:
        gateway_cwd = GATEWAY / ".build" / "next" / "standalone"
        if not (gateway_cwd / "server-ws.mjs").is_file():
            raise RuntimeError("Bundled gateway build is missing. Run kratos-studio setup first.")
        gateway_command = [node, "server-ws.mjs"]
    return ManagedService("OmniRoute", gateway_command, gateway_cwd, gateway_env, log_dir / "gateway.log")


def browser_sync_service(args: argparse.Namespace, env: dict[str, str]) -> ManagedService | None:
    """Watch the dedicated, operator-authorized profile using the same encrypted store."""
    if env.get("KRATOS_BROWSER_SESSION_SYNC", "").lower() not in ("1", "true", "yes"):
        return None
    try:
        import psutil
        pid = int((args.workspace.resolve() / ".kratos/browser-sync/sync.pid").read_text(encoding="utf-8"))
        process = psutil.Process(pid)
        if any("webSessionSync.ts" in part for part in process.cmdline()):
            return None
    except (OSError, ValueError, psutil.Error):
        pass
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required by browser session sync")
    command = [node, "--import", "tsx/esm", "scripts/ops/webSessionSync.ts", "--workspace", str(args.workspace.resolve()),
               "--data-dir", env["DATA_DIR"], "--providers", env.get("KRATOS_BROWSER_SESSION_PROVIDERS", "qwen-browser,doubao-web,kimi-web"),
               "--interval", env.get("KRATOS_BROWSER_SESSION_SYNC_INTERVAL", "30")]
    if env.get("KRATOS_BROWSER_SESSION_CDP"):
        command.extend(["--cdp", env["KRATOS_BROWSER_SESSION_CDP"]])
    return ManagedService("Browser session sync", command, GATEWAY, env,
                          args.workspace.resolve() / ".kratos/studio/logs/browser-sync.log")


def run(args: argparse.Namespace) -> None:
    if getattr(args, "cli", False):
        run_cli(args)
        return
    if args.port == args.agent_port:
        raise ValueError("Gateway and agent ports must differ")
    for port in (args.port, args.agent_port):
        if not port_available(port):
            raise RuntimeError(f"Port {port} is in use. Select free --port and --agent-port values.")
    env = prepare_environment(args)
    workspace = args.workspace.resolve()
    log_dir = workspace / ".kratos" / "studio" / "logs"
    gateway = gateway_service(args, env)
    agent = ManagedService("Kratos", [sys.executable, "-m", "kratos_agent.web.server", "--port", str(args.agent_port), "--no-browser"], workspace, env, log_dir / "agent.log")
    stop = threading.Event()
    previous = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous[sig] = signal.signal(sig, lambda *_: stop.set())
    services = [gateway, agent]
    try:
        gateway.start()
        gateway.wait_ready(env["KRATOS_GATEWAY_URL"] + "/api/health", args.startup_timeout)
        agent.start()
        agent.wait_ready(f"http://127.0.0.1:{args.agent_port}/api/health", args.startup_timeout, env["KRATOS_INTERNAL_TOKEN"])
        watcher = browser_sync_service(args, env)
        if watcher:
            watcher.start()
            services.append(watcher)
            print(f"Automatic browser-session sync enabled; see {watcher.log}", flush=True)
        url = env["KRATOS_GATEWAY_URL"] + "/dashboard/kratos"
        print(f"Kratos Studio ready: {url}", flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        while not stop.wait(0.5):
            for service in services:
                if service.process and service.process.poll() is not None:
                    if service.restarts >= 3:
                        if service.name == "Browser session sync":
                            print(f"Browser session sync needs attention; see {service.log}", flush=True)
                            service.stop()
                            services.remove(service)
                            break
                        raise RuntimeError(f"{service.name} stopped repeatedly; see {service.log}")
                    service.stop()
                    service.restarts += 1
                    print(f"Restarting {service.name} ({service.restarts}/3). Interrupted tasks require explicit resume.", flush=True)
                    service.start()
                    if service.name == "Browser session sync":
                        continue
                    ready_url = env["KRATOS_GATEWAY_URL"] + "/api/health" if service is gateway else f"http://127.0.0.1:{args.agent_port}/api/health"
                    service.wait_ready(ready_url, args.startup_timeout, env["KRATOS_INTERNAL_TOKEN"])
    finally:
        for service in reversed(services):
            service.stop()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def gateway_models(env: dict[str, str]) -> list[str]:
    """Confirm the existing listener serves the model API expected by the CLI."""
    headers = {}
    if env.get("KRATOS_API_KEY"):
        headers["Authorization"] = "Bearer " + env["KRATOS_API_KEY"]
    request = urllib.request.Request(env["KRATOS_MODEL_ENDPOINT"], headers=headers)
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=5) as response:
            payload = json.load(response)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ValueError("Invalid gateway model response")
        return [str(item["id"]) for item in payload["data"] if isinstance(item, dict) and item.get("id")]
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise RuntimeError("Cannot read gateway models. Set KRATOS_API_KEY to a key accepted by the running gateway, or restart Studio with this launcher.") from exc


def launch_terminal(workspace: Path, env: dict[str, str]) -> None:
    """Import the runtime only after workspace and gateway settings are active."""
    previous_env, previous_cwd, previous_argv = dict(os.environ), Path.cwd(), sys.argv
    try:
        os.environ.update(env)
        os.chdir(workspace)
        sys.argv = ["kratos", "--cli"]
        from kratos_agent.cli import main as cli_main
        cli_main()
    finally:
        os.chdir(previous_cwd)
        sys.argv = previous_argv
        os.environ.clear()
        os.environ.update(previous_env)


def wait_gateway_models(env: dict[str, str], timeout: float) -> list[str]:
    """Allow the model route to finish compiling, but fail auth/config errors promptly."""
    deadline = time.monotonic() + timeout
    announced = False
    while True:
        try:
            return gateway_models(env)
        except RuntimeError as exc:
            cause = exc.__cause__
            transient = isinstance(cause, OSError)
            if isinstance(cause, urllib.error.HTTPError):
                transient = cause.code >= 500
            if not transient or time.monotonic() >= deadline:
                raise
            if not announced:
                print("Waiting for the gateway model API to become ready...", flush=True)
                announced = True
            time.sleep(min(0.5, max(0, deadline - time.monotonic())))


def run_cli(args: argparse.Namespace) -> None:
    env = prepare_environment(args)
    from kratos_agent.brain.config import get_default_model, get_model_provider
    if get_model_provider() != "gateway":
        model = get_default_model()
        if not model:
            raise RuntimeError("Select a connected ChatGPT model with kratos-connect before starting Kratos.")
        env["KRATOS_MODEL"] = model
        print(f"Workspace: {args.workspace.resolve()} | Model: {model}", flush=True)
        launch_terminal(args.workspace.resolve(), env)
        return
    url = env["KRATOS_GATEWAY_URL"]
    gateway = None
    watcher = None
    try:
        if not port_available(args.port):
            if not http_ready(url + "/api/health"):
                raise RuntimeError(f"Port {args.port} is in use, but its gateway is not ready. Check Studio or select --port.")
            print(f"Connecting CLI to running gateway: {url}", flush=True)
        else:
            gateway = gateway_service(args, env)
            gateway.start()
            gateway.wait_ready(url + "/api/health", args.startup_timeout)
            print(f"CLI gateway ready: {url}", flush=True)
        models = wait_gateway_models(env, args.startup_timeout)
        model = env.get("KRATOS_MODEL", "").strip()
        if not model:
            raise RuntimeError("Set KRATOS_MODEL in the workspace .env to a model served by the gateway.")
        if model not in models:
            raise RuntimeError(f"Configured model '{model}' is not listed by this gateway. Set KRATOS_MODEL to an available model ID.")
        print(f"Workspace: {args.workspace.resolve()} | Model: {model}", flush=True)
        watcher = browser_sync_service(args, env)
        if watcher:
            watcher.start()
            print(f"Automatic browser-session sync enabled; see {watcher.log}", flush=True)
        launch_terminal(args.workspace.resolve(), env)
    finally:
        if watcher:
            watcher.stop()
        if gateway is not None:
            gateway.stop()


def setup(args: argparse.Namespace) -> None:
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("Install a supported Node.js version first")
    directories = (GATEWAY,) if args.cli else (GATEWAY, ROOT / "frontend")
    for directory in directories:
        subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=directory, check=True)
    # Some npm versions omit this optional dependency even when installation succeeds.
    if not (GATEWAY / "node_modules" / "better-sqlite3" / "package.json").is_file():
        subprocess.run([npm, "install", "better-sqlite3", "--no-save", "--foreground-scripts", "--no-audit", "--no-fund"], cwd=GATEWAY, check=True)
    subprocess.run([npm, "run", "check:native-deps"], cwd=GATEWAY, check=True)
    if not args.cli:
        subprocess.run([npm, "run", "build"], cwd=ROOT / "frontend", check=True)
    if not args.dev:
        subprocess.run([npm, "run", "build"], cwd=GATEWAY, check=True)


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "browser-sync":
        node = shutil.which("node")
        if not node:
            raise SystemExit("Node.js is required by browser session sync")
        forwarded = list(argv[1:])
        if "--workspace" in forwarded:
            position = forwarded.index("--workspace") + 1
            if position < len(forwarded):
                forwarded[position] = str(Path(forwarded[position]).resolve())
        elif not any(part.startswith("--workspace=") for part in forwarded):
            forwarded.extend(["--workspace", str(Path.cwd())])
        for position, part in enumerate(forwarded):
            if part.startswith("--workspace="):
                forwarded[position] = "--workspace=" + str(Path(part.split("=", 1)[1]).resolve())
        raise SystemExit(subprocess.call([node, "--import", "tsx/esm", "scripts/ops/webSessionSync.ts", *forwarded], cwd=GATEWAY))
    if argv and argv[0] == "mcp":
        from kratos_agent.mcp_cli import main as mcp_main
        raise SystemExit(mcp_main(argv[1:]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "cli", "setup", "doctor", "import-data"), nargs="?", default="run")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--source-data-dir", type=Path, help="Existing OmniRoute DATA_DIR for import-data")
    parser.add_argument("--source-env", type=Path, help="Existing OmniRoute .env with STORAGE_ENCRYPTION_KEY")
    parser.add_argument("--port", type=int, default=20128)
    parser.add_argument("--agent-port", type=int, default=7860)
    parser.add_argument("--startup-timeout", type=float, default=600)
    parser.add_argument("--dev", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--cli", action="store_true", help="Run the terminal agent; setup builds only its gateway dependencies")
    args = parser.parse_args(argv)
    if args.action == "cli":
        args.cli = True
    if args.action == "setup":
        setup(args)
    elif args.action == "import-data":
        if not args.source_data_dir or not args.source_env:
            parser.error("import-data requires --source-data-dir and --source-env")
        if not port_available(args.port) or not port_available(args.agent_port):
            raise RuntimeError("Stop Kratos Studio before importing data")
        from kratos_agent.data_transfer import import_omniroute_data
        target = args.data_dir or args.workspace / ".kratos" / "studio" / "gateway"
        print(json.dumps(import_omniroute_data(args.source_data_dir, target, args.source_env), indent=2))
    elif args.action == "doctor":
        print(json.dumps({"root": str(ROOT), "gateway_source": (GATEWAY / "package.json").is_file(), "node": shutil.which("node"), "python": sys.executable, "frontend_built": (ROOT / "frontend/dist/index.html").is_file(), "gateway_built": (GATEWAY / ".build/next/BUILD_ID").is_file() and (GATEWAY / ".build/next/standalone/server-ws.mjs").is_file(), "credentials_file": str((args.data_dir.resolve() if args.data_dir else args.workspace.resolve() / ".kratos/studio/gateway") / "studio-secrets.json")}, indent=2))
    else:
        try:
            run(args)
        except RuntimeError as exc:
            parser.exit(1, f"Kratos Studio: {exc}\n")


if __name__ == "__main__":
    main()
