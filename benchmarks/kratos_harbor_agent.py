"""Harbor adapter for exercising the real Kratos runtime on Terminal-Bench tasks.

Kratos runs on the host, while every command requested by the model is executed
inside Harbor's disposable task environment. Credentials stay on the host.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import re
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
from harbor.agents.base import BaseAgent
from harbor.agents.options import AgentOptions
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from pydantic import Field


class KratosHarborOptions(AgentOptions):
    """Validated user-facing options for a bounded Harbor run."""

    max_steps: int = Field(default=48, ge=1, le=64)


class KratosHarborAgent(BaseAgent):
    """Run Kratos in Sovereign mode with a single container-backed shell tool."""

    options_model = KratosHarborOptions

    @staticmethod
    def name() -> str:
        return "kratos"

    @staticmethod
    def version() -> str:
        return "0.1.0"

    @staticmethod
    def _requested_app_paths(instruction: str) -> list[str]:
        """Extract explicit /app deliverables so the harness can detect stalled work."""
        matches = re.findall(r"(?<![A-Za-z0-9_.-])(/app/[A-Za-z0-9_./-]+\.[A-Za-z0-9_-]+)", instruction)
        return list(dict.fromkeys(path.rstrip(".,:;)") for path in matches))

    async def setup(self, environment: BaseEnvironment) -> None:
        # Kratos is installed in the host project environment by the runner.
        # Do not copy provider credentials into the task container.
        del environment

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        project_root = Path(__file__).resolve().parents[1]
        load_dotenv(project_root / ".env", override=False)

        # Preserve Kratos's configured OmniRoute endpoint and credential.
        if os.getenv("OMNIROUTE_BASE_URL"):
            os.environ["BRAIN_BASE_URL"] = os.environ["OMNIROUTE_BASE_URL"]
        model_name = (
            os.getenv("KRATOS_BENCH_MODEL")
            or os.getenv("OMNIROUTE_MODEL")
            or os.getenv("BRAIN_MODEL")
            or os.getenv("KRATOS_MODEL")
            or "ds-web/deepseek-v4-pro-think"
        )
        os.environ["BRAIN_MODEL"] = model_name
        os.environ["KRATOS_MODEL"] = model_name
        os.environ["NORMAL_MODE_MODEL"] = model_name
        max_steps = max(
            1,
            min(
                64,
                int(os.getenv("KRATOS_BENCH_MAX_STEPS", str(self.options.max_steps))),
            ),
        )

        # Import after entering a throwaway workspace because main.py creates a
        # module-level runtime at import time.
        with tempfile.TemporaryDirectory(prefix="kratos-harbor-") as scratch:
            scratch_path = Path(scratch).resolve()
            old_cwd = Path.cwd()
            os.chdir(scratch_path)
            try:
                from kratos_agent.core.approval_mode import ApprovalMode, approval_gate
                from kratos_agent.core.instruction_engine import InstructionEngine, InstructionModule
                from kratos_agent.core.runtime_contracts import ChatMessage
                kratos_main = importlib.import_module("kratos_agent.main")

                runtime = kratos_main.runtime
                runtime.workspace = scratch_path
                runtime.set_model(model_name)
                runtime.clear_cancel()
                runtime.loop.tool_platform = "linux"
                runtime.loop.tool_cwd = "/app"
                approval_gate.set_mode(ApprovalMode.SOVEREIGN)
                # The process-global runtime may restore the user's interactive
                # history and memory at import. A benchmark must receive only
                # its own task context and must not persist turns into that store.
                benchmark_instructions = InstructionEngine()
                benchmark_instructions.register(InstructionModule(
                    "terminal-benchmark-agent",
                    "system",
                    lambda: (
                        "You are Kratos, an autonomous coding agent working only in the isolated task container. "
                        "Use the supplied shell tool to inspect, create or edit files, and run tests. "
                        "Do not rely on any prior conversation or external workspace context."
                    ),
                    5,
                ))
                benchmark_instructions.register(InstructionModule(
                    "terminal-benchmark-execution-discipline",
                    "developer",
                    lambda: (
                        "BENCHMARK EXECUTION: Complete the requested deliverable directly. "
                        "Use no more than two short environment-inspection commands. Then create or edit the required files. "
                        "Do not spend turns testing hypothetical libraries or synthetic examples before implementation. "
                        "Run the task's provided verifier or a focused test after implementation, fix failures from their output, "
                        "and confirm the required artifact exists before reporting completion."
                    ),
                    13,
                ))
                runtime.instructions = benchmark_instructions
                runtime.loop.instructions = benchmark_instructions
                runtime._current_tool_calls = []

                registered = runtime.tools_registry._tools
                terminal = registered.get("run_terminal_command")
                if terminal is None:
                    raise RuntimeError("Kratos did not register run_terminal_command")

                # Keep model-visible capabilities narrow: all benchmark actions
                # must pass through the container environment's shell API.
                runtime.tools_registry._tools = {"run_terminal_command": terminal}

                # Keep a compact event trace beside Harbor's agent logs. This
                # makes model/tool loops diagnosable even when a trial raises
                # before Harbor can persist AgentContext metadata.
                trace_path = self.logs_dir / "kratos-events.jsonl"
                trace_path.parent.mkdir(parents=True, exist_ok=True)
                original_emit = runtime._emit
                traceable_events = {
                    "model.response",
                    "tool.started",
                    "tool.completed",
                    "tool.failed",
                    "turn.failed",
                }

                def emit_with_trace(event: Any) -> None:
                    original_emit(event)
                    kind = getattr(event.kind, "value", str(event.kind))
                    if kind not in traceable_events:
                        return
                    payload = dict(event.payload or {})
                    if kind in {"tool.completed", "tool.failed"}:
                        payload["content"] = str(payload.get("content", ""))[:1200]
                    with trace_path.open("a", encoding="utf-8") as trace_file:
                        trace_file.write(json.dumps({"kind": kind, "payload": payload}, ensure_ascii=False, default=str) + "\n")

                runtime._emit = emit_with_trace

                event_loop = asyncio.get_running_loop()
                requested_app_paths = self._requested_app_paths(instruction)
                shell_calls = 0

                def execute_in_task_container(command: str = "", **_: Any) -> str:
                    nonlocal shell_calls
                    shell_calls += 1
                    future = asyncio.run_coroutine_threadsafe(
                        environment.exec(
                            command,
                            timeout_sec=int(os.getenv("KRATOS_BENCH_COMMAND_TIMEOUT", "180")),
                        ),
                        event_loop,
                    )
                    result = future.result(timeout=190)
                    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
                    if shell_calls in (6, 12, 18, 24) and requested_app_paths:
                        missing: list[str] = []
                        for app_path in requested_app_paths:
                            check = asyncio.run_coroutine_threadsafe(
                                environment.exec(f"test -f {app_path}"),
                                event_loop,
                            ).result(timeout=20)
                            if check.return_code:
                                missing.append(app_path)
                        if missing:
                            output += (
                                "\n[Progress check] Required deliverable(s) not created yet: "
                                + ", ".join(missing)
                                + ". Stop further environment/parser experiments; create the requested file(s) from the findings so far, then run the task verifier."
                            )
                    if result.return_code:
                        return f"Command exited with status {result.return_code}.\n{output}".strip()
                    return output or "Command completed successfully with no output."

                terminal.handler = execute_in_task_container

                # run_agent is synchronous; use a worker so the Harbor asyncio
                # loop can service each bridged environment.exec call.
                with ThreadPoolExecutor(max_workers=1, thread_name_prefix="kratos-agent") as pool:
                    result = await asyncio.get_running_loop().run_in_executor(
                        pool,
                        partial(
                            runtime.loop.run,
                            [ChatMessage(role="user", content=instruction)],
                            runtime._allow_tool,
                            max_steps=max_steps,
                        ),
                    )
                if isinstance(result, tuple):
                    result = result[0]
                runtime._emit = original_emit

                context.metadata = {
                    **(context.metadata or {}),
                    "kratos_model": model_name,
                    "kratos_mode": approval_gate.mode.value,
                    "kratos_result_chars": len(result),
                    "kratos_tool_calls": len(runtime._current_tool_calls),
                    "kratos_agent_max_steps": max_steps,
                    "kratos_result_status": "error" if result.startswith(("Model request failed:", "Execution error:", "Stopped after ")) else "completed",
                }
                if context.metadata["kratos_result_status"] == "error":
                    raise RuntimeError(result)
            finally:
                if "original_emit" in locals():
                    runtime._emit = original_emit
                os.chdir(old_cwd)
