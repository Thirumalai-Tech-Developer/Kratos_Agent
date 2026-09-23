from __future__ import annotations

from typing import Any, Dict


class CodeExecutor:
    def __init__(self, runtime: Any = None) -> None:
        self.runtime = runtime

    def run_agent(self, mission: str) -> Dict[str, Any]:
        if self.runtime is None:
            from kratos_agent.main import runtime as default_runtime
            self.runtime = default_runtime
        output = self.runtime.run_agent(mission, agent_mode=True)
        failed = str(output).startswith(("Model request failed:", "Execution error:"))
        return {"ok": not failed, "verified": not failed, "message": str(output)}
