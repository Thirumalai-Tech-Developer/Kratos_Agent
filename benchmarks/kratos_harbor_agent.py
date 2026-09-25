"""Harbor adapter for exercising the real Kratos runtime on Terminal-Bench tasks.

Kratos runs on the host, while every command requested by the model is executed
inside Harbor's disposable task environment. Credentials stay on the host.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext


class KratosHarborAgent(BaseAgent):
    """Run Kratos in Sovereign mode with a single container-backed shell tool."""

    @staticmethod
    def name() -> str:
        return "kratos"

    @staticmethod
    def version() -> str:
        return "0.1.0"

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

        # Import after entering a throwaway workspace because main.py creates a
        # module-level runtime at import time.
        with tempfile.TemporaryDirectory(prefix="kratos-harbor-") as scratch:
            scratch_path = Path(scratch).resolve()
            old_cwd = Path.cwd()
            os.chdir(scratch_path)
            try:
                from kratos_agent.core.approval_mode import ApprovalMode, approval_gate
                kratos_main = importlib.import_module("kratos_agent.main")

                runtime = kratos_main.runtime
                runtime.workspace = scratch_path
                runtime.set_model(model_name)
                runtime.clear_cancel()
                approval_gate.set_mode(ApprovalMode.SOVEREIGN)

                registered = runtime.tools_registry._tools
                terminal = registered.get("run_terminal_command")
                if terminal is None:
                    raise RuntimeError("Kratos did not register run_terminal_command")

                # Keep model-visible capabilities narrow: all benchmark actions
                # must pass through the container environment's shell API.
                runtime.tools_registry._tools = {"run_terminal_command": terminal}

                event_loop = asyncio.get_running_loop()

                def execute_in_task_container(command: str = "", **_: Any) -> str:
                    future = asyncio.run_coroutine_threadsafe(
                        environment.exec(
                            command,
                            timeout_sec=int(os.getenv("KRATOS_BENCH_COMMAND_TIMEOUT", "180")),
                        ),
                        event_loop,
                    )
                    result = future.result(timeout=190)
                    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
                    if result.return_code:
                        return f"Command exited with status {result.return_code}.\n{output}".strip()
                    return output or "Command completed successfully with no output."

                terminal.handler = execute_in_task_container

                # run_agent is synchronous; use a worker so the Harbor asyncio
                # loop can service each bridged environment.exec call.
                with ThreadPoolExecutor(max_workers=1, thread_name_prefix="kratos-agent") as pool:
                    result = await asyncio.get_running_loop().run_in_executor(
                        pool, runtime.run_agent, instruction
                    )

                context.metadata = {
                    **(context.metadata or {}),
                    "kratos_model": model_name,
                    "kratos_mode": approval_gate.mode.value,
                    "kratos_result_chars": len(result),
                    "kratos_tool_calls": len(runtime._current_tool_calls),
                    "kratos_result_status": "error" if result.startswith(("Model request failed:", "Execution error:")) else "completed",
                }
                if context.metadata["kratos_result_status"] == "error":
                    raise RuntimeError(result)
            finally:
                os.chdir(old_cwd)
