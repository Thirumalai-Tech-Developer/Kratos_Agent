"""Low-overhead Terminal-Bench adapter for Kratos.

Terminal-Bench measures task completion. Kratos' interactive planner is useful
for normal work, but a separate planner LLM call adds latency and tokens before
the first real tool call. This adapter keeps the real Kratos execution loop,
tool registry, verification, and Harbor isolation while removing only that
benchmark-specific planning round-trip.
"""
from __future__ import annotations

from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

import kratos_agent.core.agent_loop as agent_loop_module
from benchmarks.kratos_harbor_agent import KratosHarborAgent


class KratosHarborFastAgent(KratosHarborAgent):
    """Run Kratos' real execution loop without the extra planning request."""

    @staticmethod
    def name() -> str:
        return "kratos-fast"

    @staticmethod
    def version() -> str:
        return "0.2.0"

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        original_planner = agent_loop_module.formulate_agent_plan
        agent_loop_module.formulate_agent_plan = lambda **_: None
        try:
            await super().run(instruction, environment, context)
        finally:
            agent_loop_module.formulate_agent_plan = original_planner
