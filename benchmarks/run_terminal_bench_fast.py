"""Run a low-overhead Terminal-Bench 4.0.0 pilot through Harbor."""
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


def _model() -> str:
    return (
        os.getenv("KRATOS_BENCH_MODEL")
        or os.getenv("OMNIROUTE_MODEL")
        or os.getenv("BRAIN_MODEL")
        or os.getenv("KRATOS_MODEL")
        or "ds-web/deepseek-v4-pro-think"
    )


def preflight_provider() -> int:
    """Fail in seconds on gateway/auth problems instead of burning Harbor time."""
    key = (os.getenv("OMNI_KEY") or os.getenv("BRAIN_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        print("Provider preflight failed: no API key configured (OMNI_KEY/BRAIN_KEY/OPENAI_API_KEY).", file=sys.stderr)
        return 2

    url = f"{_base_url()}/models"
    request = Request(url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=5) as response:
            if not 200 <= response.status < 300:
                print(f"Provider preflight failed: HTTP {response.status} from {url}", file=sys.stderr)
                return 3
    except HTTPError as exc:
        print(f"Provider preflight failed: HTTP {exc.code} from {url}. Check gateway credentials.", file=sys.stderr)
        return 3
    except (URLError, TimeoutError) as exc:
        detail = getattr(exc, "reason", str(exc))
        print(f"Provider preflight failed: {detail}. Is the gateway reachable at {url}?", file=sys.stderr)
        return 3
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="validate Harbor task metadata without a provider call")
    parser.add_argument("--skip-provider-preflight", action="store_true", help="skip the fast gateway/auth check")
    parser.add_argument("--task", action="append", choices=TASKS, help="select one or more pilot tasks")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env", override=False)
    tasks = tuple(args.task) if args.task else TASKS
    jobs_dir = Path(os.getenv("KRATOS_BENCH_JOBS_DIR", ROOT / "benchmarks" / "jobs")).resolve()

    if not args.dry_run and not args.skip_provider_preflight:
        status = preflight_provider()
        if status:
            return status

    model = _model()
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

    failures = 0
    for task in tasks:
        print(f"\n=== {task} ===")
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
            "--job-name", f"kratos-tb4-fast-{task.rsplit('/', 1)[-1]}-{run_id}",
            "--jobs-dir", str(jobs_dir),
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
            failures += 1
            print(f"Task failed to execute: {task} (exit={result.returncode})", file=sys.stderr)

    if failures:
        print(f"\nBenchmark completed with {failures}/{len(tasks)} task execution failures.", file=sys.stderr)
        return 10
    print(f"\nBenchmark completed: {len(tasks)}/{len(tasks)} task runs returned successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
