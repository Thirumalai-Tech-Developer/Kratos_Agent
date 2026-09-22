"""Central ComputerManager orchestrating observe, plan, act, verify, and recover."""
from __future__ import annotations
import time
from typing import Any, Dict, List, Optional

from kratos_agent.computer.state import ComputerState, ComputerAction, ActionResult
from kratos_agent.computer.observer import get_observer
from kratos_agent.computer.executor import get_executor
from kratos_agent.computer.verifier import get_verifier
from kratos_agent.computer.planner import ComputerPlanner
from kratos_agent.computer.capabilities import probe_capabilities


class ComputerManager:
    """Universal Computer Use Engine runtime orchestrator."""

    def __init__(self) -> None:
        import threading
        self.observer = get_observer()
        self.executor = get_executor()
        self.verifier = get_verifier()
        self.planner = ComputerPlanner()
        self._execution_lock = threading.Lock()

    def observe(
        self,
        include_interactive: bool = True,
        max_elements: int = 150,
        force_refresh: bool = False,
        targeted_query: Optional[str] = None,
    ) -> ComputerState:
        """Captures the current state of the computer environment with state caching."""
        return self.observer.observe(
            include_interactive=include_interactive,
            max_elements=max_elements,
            force_refresh=force_refresh,
            targeted_query=targeted_query,
        )

    def execute_action(self, action: ComputerAction) -> ActionResult:
        """Executes a single computer action with before/after state verification (§50)."""
        with self._execution_lock:
            before = self.observe(include_interactive=False)
            result = self.executor.execute(action)

            # Invalidate cache for mutating actions
            from kratos_agent.computer.state_cache import get_state_cache
            get_state_cache().invalidate()

            time.sleep(0.1)
            after = self.observe(include_interactive=False, force_refresh=True)

        # Verify action
        verified, detail = self.verifier.verify_action(
            action=action.action,
            before_state=before,
            after_state=after,
            expected_state=action.expected_state,
        )
        result.verified = verified
        if not verified and result.ok:
            result.detail = f"Action executed, but verification warning: {detail}"

        return result

    def run_task(self, goal: str, max_steps: int = 20) -> ActionResult:
        """Executes a multi-step autonomous computer task with closed-loop verification."""
        initial_state = self.observe()
        plan = self.planner.plan_task(goal, initial_state)

        if not plan:
            return ActionResult(ok=False, action="computer_task", detail=f"Could not generate action plan for goal: '{goal}'")

        step_results = []
        for step_idx, action in enumerate(plan[:max_steps], start=1):
            res = self.execute_action(action)
            step_results.append(res.to_dict())
            if not res.ok:
                return ActionResult(
                    ok=False,
                    action="computer_task",
                    detail=f"Task failed at step {step_idx} ({action.action}): {res.detail}",
                    data={"steps_completed": step_idx - 1, "results": step_results},
                )

        return ActionResult(
            ok=True,
            action="computer_task",
            detail=f"Successfully executed task with {len(step_results)} steps",
            data={"results": step_results},
            verified=True,
        )

    def get_capabilities(self) -> Dict[str, Any]:
        """Returns the detected capabilities of the computer engine."""
        return probe_capabilities()


_computer_manager: Optional[ComputerManager] = None


def get_computer_manager() -> ComputerManager:
    global _computer_manager
    if _computer_manager is None:
        _computer_manager = ComputerManager()
    return _computer_manager
