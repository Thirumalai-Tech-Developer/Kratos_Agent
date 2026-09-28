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
from kratos_agent.brain.config import get_api_key, get_default_model, get_model_endpoint_url

ROOT = Path(__file__).resolve().parents[1]
TASKS = (
    "terminal-bench/html-js-filter",
    "terminal-bench/photonic-waveguide-routing",
    "terminal-bench/bun-sourcemap-leak",
)
DEFAULT_VERIFIER_TIMEOUT_MULTIPLIER = 2.0


def _model_endpoint_url() -> str:
    return get_model_endpoint_url()


def _model() -> str:
    return get_default_model()


def preflight_kratos_gateway() -> int:
    """Fail quickly on gateway configuration or connectivity errors."""
    key = get_api_key()

    url = _model_endpoint_url()
    headers = {"Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=5) as response:
            if not 200 <= response.status < 300:
                print(f"Kratos gateway preflight failed: HTTP {response.status} from {url}", file=sys.stderr)
                return 3
    except HTTPError as exc:
        print(f"Kratos gateway preflight failed: HTTP {exc.code} from {url}. Check the gateway configuration.", file=sys.stderr)
        return 3
    except (URLError, TimeoutError) as exc:
        detail = getattr(exc, "reason", str(exc))
        print(f"Kratos gateway preflight failed: {detail}. Is the gateway reachable at {url}?", file=sys.stderr)
        return 3
    return 0


def _build_harbor_command(
    *,
    task: str,
    model: str,
    jobs_dir: Path,
    run_id: str,
    agent_timeout_multiplier: float,
    verifier_timeout_multiplier: float,
    dry_run: bool = False,
) -> list[str]:
    command = [
        "harbor", "run",
        "--agent", "benchmarks.kratos_harbor_fast_agent:KratosHarborFastAgent",
        "--model", model,
        "--dataset", "terminal-bench/terminal-bench@4.0.0",
        "--include-task-name", task,
        "--n-tasks", "1",
        "--n-attempts", "1",
        "--n-concurrent", "1",
        "--agent-timeout-multiplier", str(agent_timeout_multiplier),
        "--verifier-timeout-multiplier", str(verifier_timeout_multiplier),
        "--job-name", f"kratos-tb4-fast-{task.rsplit('/', 1)[-1]}-{run_id}",
        "--jobs-dir", str(jobs_dir),
        "--yes",
    ]
    if dry_run:
        command.append("--dry-run")
    return command


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="validate Harbor task metadata without a provider call")
    parser.add_argument("--skip-gateway-preflight", action="store_true", help="skip the fast Kratos gateway check")
    parser.add_argument("--task", action="append", choices=TASKS, help="select one or more pilot tasks")
    parser.add_argument(
        "--verifier-timeout-multiplier",
        type=float,
        default=DEFAULT_VERIFIER_TIMEOUT_MULTIPLIER,
        help=(
            "Multiplier for Terminal-Bench verifier timeouts. The html-js-filter "
            "browser verifier can legitimately take several minutes."
        ),
    )
    args = parser.parse_args()

    if args.verifier_timeout_multiplier <= 0:
        parser.error("--verifier-timeout-multiplier must be greater than 0")

    load_dotenv(ROOT / ".env", override=False)
    tasks = tuple(args.task) if args.task else TASKS
    jobs_dir = Path(os.getenv("KRATOS_BENCH_JOBS_DIR", ROOT / "benchmarks" / "jobs")).resolve()
    model = _model()
    if not model:
        print("Set KRATOS_MODEL to the exact model ID served by the Kratos gateway.", file=sys.stderr)
        return 2

    if not args.dry_run and not args.skip_gateway_preflight:
        status = preflight_kratos_gateway()
        if status:
            return status

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
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
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
        command = _build_harbor_command(
            task=task,
            model=model,
            jobs_dir=jobs_dir,
            run_id=run_id,
            agent_timeout_multiplier=600 / 3_600,
            verifier_timeout_multiplier=args.verifier_timeout_multiplier,
            dry_run=args.dry_run,
        )
        try:
            result = subprocess.run(command, cwd=ROOT, env=env, check=False)
        except FileNotFoundError:
            print("Harbor CLI not found. Run with uv run --extra benchmark.", file=sys.stderr)
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
