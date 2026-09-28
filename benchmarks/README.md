# Kratos Terminal-Bench pilot

This folder contains a small, reproducible pilot for evaluating the real Kratos
runtime with the official Terminal-Bench 2.0 task format and Harbor harness.

## Run

From the repository root, set `KRATOS_MODEL` to the exact ID served by your
Kratos gateway in `.env`. Set `KRATOS_API_KEY` only if the gateway requires it.
Ensure Docker Desktop is running, then run:

```powershell
uv run --extra benchmark python benchmarks/run_terminal_bench.py
```

Use `uv run --extra benchmark python benchmarks/run_terminal_bench.py --dry-run`
to ask Harbor to validate task metadata and the custom adapter without a model
request. Harbor may still require a reachable local Docker daemon for its preflight.

The default run uses the configured Kratos model and one attempt each on three tasks from the official `terminal-bench/terminal-bench@4.0.0`
tasks: `html-js-filter`, `photonic-waveguide-routing`, and `bun-sourcemap-leak`.
It caps each task at ten minutes and runs trials sequentially. Job output is
written under `benchmarks/jobs/` (or `KRATOS_BENCH_JOBS_DIR` if set).

Kratos uses Sovereign mode inside a temporary host-side workspace. The agent is
exposed to only its shell tool; every requested shell command is executed in the
task's disposable Harbor environment. Provider credentials stay on the host.
The benchmark runner does not upload jobs or publish leaderboard results. It does
not select or call a separate model provider.

## Scope

This is a three-task pilot, not a Terminal-Bench leaderboard submission and not
a statistically reliable comparison with other agents. Report the exact task
set, model, attempt count, and pass rate alongside any public result.
