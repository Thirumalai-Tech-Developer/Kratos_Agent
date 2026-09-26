"""Run the pinned official Terminal-Bench 2.0 (4.0.0) subset through Harbor."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
TASKS = (
    "terminal-bench/html-js-filter",
    "terminal-bench/photonic-waveguide-routing",
    "terminal-bench/bun-sourcemap-leak",
)
JOBS_DIR = Path(os.getenv("KRATOS_BENCH_JOBS_DIR", ROOT / "benchmarks" / "jobs")).resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate task selection and the custom Harbor agent without a provider call",
    )
    parser.add_argument(
        "--task",
        action="append",
        choices=TASKS,
        help="select a task from the pilot set; repeat to select more than one",
    )
    args = parser.parse_args()
    tasks = tuple(args.task) if args.task else TASKS
    load_dotenv(ROOT / ".env", override=False)
    if not os.getenv("OMNI_KEY"):
        print("No OMNI_KEY is configured; cannot run Kratos through OmniRoute.", file=sys.stderr)
        return 2
    model = (
        os.getenv("KRATOS_BENCH_MODEL")
        or os.getenv("OMNIROUTE_MODEL")
        or os.getenv("BRAIN_MODEL")
        or os.getenv("KRATOS_MODEL")
        or "ds-web/deepseek-v4-pro-think"
    )

    if args.dry_run:
        print("Harbor dry-run validates the selected task metadata and custom agent without calling OmniRoute.")
    else:
        # The environment runner requires Docker; fail before starting Harbor if it
        # is unavailable, rather than recording setup failures as agent failures.
        docker = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if docker.returncode:
            detail = (docker.stderr or docker.stdout).strip()
            print(f"Docker engine is unavailable; Harbor task containers cannot start. {detail}", file=sys.stderr)
            return 3

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["KRATOS_BENCH_MODEL"] = model
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    print(f"Terminal-Bench 4.0.0 | model={model} | attempts=1 | tasks={len(tasks)} | mode=Sovereign")
    print("Task commands are routed through Harbor's disposable Docker environments.")
    for task in tasks:
        command = [
            "harbor", "run",
            "--agent", "benchmarks.kratos_harbor_agent:KratosHarborAgent",
            "--model", model,
            "--dataset", "terminal-bench/terminal-bench@4.0.0",
            "--include-task-name", task,
            "--n-tasks", "1",
            "--n-attempts", "1",
            "--n-concurrent", "1",
            "--agent-timeout-multiplier", str(600 / 3_600),
            "--quiet",
            "--job-name", f"kratos-tb4-{task.rsplit('/', 1)[-1]}-{run_id}",
            "--jobs-dir", str(JOBS_DIR),
            "--yes",
        ]
        if args.dry_run:
            command.append("--dry-run")
        try:
            if args.dry_run:
                result = subprocess.run(
                    command, cwd=ROOT, env=env, check=False, capture_output=True, text=True
                )
                if result.stdout:
                    print(result.stdout, end="")
                if result.stderr:
                    print(result.stderr, end="", file=sys.stderr)
            else:
                result = subprocess.run(command, cwd=ROOT, env=env, check=False)
        except FileNotFoundError:
            print("Harbor CLI not found. Run this script with `uv run --extra benchmark ...`.", file=sys.stderr)
            return 4
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
