"""Run a fair, low-overhead Terminal-Bench 2.0 pilot through Harbor."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
TASKS = (
    "terminal-bench/html-js-filter",
    "terminal-bench/photonic-waveguide-routing",
    "terminal-bench/bun-sourcemap-leak",
)
JOBS_DIR = Path(os.getenv("KRATOS_BENCH_JOBS_DIR", ROOT / "benchmarks" / "jobs")).resolve()


def _base_url() -> str:
    endpoint = (
        os.getenv("BRAIN_BASE_URL")
        or os.getenv("OMNIROUTE_BASE_URL")
        or os.getenv("CHAT_BASE_URL")
        or "http://127.0.0.1:20128/v1"
    ).rstrip("/")
    if endpoint.endswith("/chat/completions"):
        endpoint = endpoint[: -len("/chat/completions")]
    return endpoint


def preflight_provider() -> int:
    """Fail fast on gateway/auth problems instead of burning Harbor task time."""
    key = (os.getenv("OMNI_KEY") or os.getenv("BRAIN_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        print("No provider API key is configured (OMNI_KEY/BRAIN_KEY/OPENAI_API_KEY).", file=sys.stderr)
        return 2

    url = f"{_base_url()}/models"
    request = Request(url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=5) as response:
            if response.status < 200 or response.status >= 300:
                print(f"Provider preflight failed: HTTP {response.status} from {url}", file=sys.stderr)
                return 3
    except HTTPError as exc:
        print(f"Provider preflight failed: HTTP {exc.code} from {url}. Check OMNI_KEY and gateway auth.", file=sys.stderr)
        return 3
    except URLError as exc:
        print(f"Provider preflight failed: {exc.reason}. Is OmniRoute reachable at {url}?", file=sys.stderr)
        return 3
    except TimeoutError:
        print(f"Provider preflight timed out after 5s: {url}", file=sys.stderr)
        return 3
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="validate Harbor task metadata without a provider call")
    parser.add_argument("--skip-provider-preflight", action="store_true", help="skip the fast gateway/auth check")
    parser.add_argument("--task", action="append", choices=TASKS, help="select one or more pilot tasks")
    args = parser.parse_args()
    tasks = tuple(args.task) if args.task else TASKS

    load_dotenv(ROOT / ".env", override=False)
    if not args.dry_run and not args.skip_provider_preflight:
        status = preflight_provider()
        if status:
            return status

    model = (
        os.getenv("KRATOS_BENCH_MODEL")
        or os.getenv("OMNIROUTE_MODEL")
        or os.getenv("BRAIN_MODEL")
        or os.getenv("KRATOS_MODEL")
        or "ds-web/deepseek-v4-pro-think"
    )

    if not args.dry_run:
        docker = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if docker.returncode:
            detail = (docker.stderr or docker.stdout).strip()
            print(f"Docker engine is unavailable; Harbor cannot start. {detail}", file=sys.stderr)
            return 4

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["KRATOS_BENCH_MODEL"] = model
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    print(
        f"Terminal-Bench 4.0.0 | model={model} | attempts=1 | tasks={len(tasks)} | "
        "agent=kratos-fast | planner_call=disabled"
    )
    for task in tasks:
        command = [
            "harbor", "run",
            "--agent", "benchmarks.kratos_harbor_fast_agent:KratosHarborFastAgent",
            "--model", model,
            "--dataset", "terminal-bench/terminal-bench@4.0.0",
            "--include-task-name", task,
            "--n-tasks", "1",
            "--n-attempts", "1",
            "--n-concurrent", "1",
            "--agent-timeout-multiplier", str(600 / 3_600),
            "--quiet",
            "--job-name", f"kratos-tb4-fast-{task.rsplit('/', 1)[-1]}-{run_id}",
            "--jobs-dir", str(JOBS_DIR),
            "--yes",
        ]
        if args.dry_run:
            command.append("--dry-run")
        try:
            result = subprocess.run(command, cwd=ROOT, env=env, check=False)
        except FileNotFoundError:
            print("Harbor CLI not found. Run with `uv run --extra benchmark ...`.", file=sys.stderr)
            return 5
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
