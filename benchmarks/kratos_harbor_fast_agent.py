"""Low-overhead Terminal-Bench adapter for Kratos.

The benchmark should measure the execution loop, not an avoidable second planning
request. This adapter disables only the benchmark-side planning call and restores
the process-global runtime after every Harbor task.
"""
from __future__ import annotations

from typing import Any

from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

import kratos_agent.core.agent_loop as agent_loop_module
from benchmarks.kratos_harbor_agent import KratosHarborAgent


class KratosHarborFastAgent(KratosHarborAgent):
    """Run Kratos' execution loop without the extra benchmark planning round-trip."""

    @staticmethod
    def name() -> str:
        return "kratos-fast"

    @staticmethod
    def version() -> str:
        return "0.3.0"

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        original_planner = agent_loop_module.formulate_agent_plan
        agent_loop_module.formulate_agent_plan = lambda **_: None

        # Kratos' runtime is process-global. Snapshot every mutable benchmark
        # override so a multi-task Harbor process cannot contaminate the next task.
        runtime: Any = None
        snapshots: dict[str, Any] = {}
        try:
            # Importing the base adapter already imports the runtime only inside run().
            import importlib
            runtime = importlib.import_module("kratos_agent.main").runtime
            snapshots = {
                "workspace": runtime.workspace,
                "instructions": runtime.instructions,
                "loop_instructions": runtime.loop.instructions,
                "tool_platform": runtime.loop.tool_platform,
                "tool_cwd": runtime.loop.tool_cwd,
                "tools": runtime.tools_registry._tools,
                "tool_calls": list(runtime._current_tool_calls),
                "emit": runtime._emit,
            }
            await super().run(instruction, environment, context)
        finally:
            try:
                if runtime is not None:
                    runtime.workspace = snapshots.get("workspace", runtime.workspace)
                    runtime.instructions = snapshots.get("instructions", runtime.instructions)
                    runtime.loop.instructions = snapshots.get("loop_instructions", runtime.loop.instructions)
                    runtime.loop.tool_platform = snapshots.get("tool_platform", runtime.loop.tool_platform)
                    runtime.loop.tool_cwd = snapshots.get("tool_cwd", runtime.loop.tool_cwd)
                    if "tools" in snapshots:
                        runtime.tools_registry._tools = snapshots["tools"]
                    if "tool_calls" in snapshots:
                        runtime._current_tool_calls = snapshots["tool_calls"]
                    if "emit" in snapshots:
                        runtime._emit = snapshots["emit"]
            finally:
                agent_loop_module.formulate_agent_plan = original_planner
