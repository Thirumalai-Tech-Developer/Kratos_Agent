"""Isolated subagent orchestration with structured, persisted results."""
from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from .runtime_contracts import ChatMessage


@dataclass
class SubagentResult:
    agent_id: str
    role: str
    task: str
    summary: str
    error: str | None = None
    duration_ms: int = 0


class SubagentManager:
    """Creates fresh histories, so exploration does not pollute the parent context."""
    def __init__(self, run_isolated: Callable[[str, list[ChatMessage]], str]) -> None:
        self.run_isolated = run_isolated

    def run(self, role: str, task: str) -> SubagentResult:
        started, agent_id = time.monotonic(), uuid.uuid4().hex
        prompt = f"You are the Kratos {role} subagent. Return a concise structured report for the parent.\n\nTask: {task}"
        try:
            summary = self.run_isolated(role, [ChatMessage("user", prompt)])
            return SubagentResult(agent_id, role, task, summary, duration_ms=int((time.monotonic() - started) * 1000))
        except Exception as exc:
            return SubagentResult(agent_id, role, task, "", error=str(exc), duration_ms=int((time.monotonic() - started) * 1000))

    def run_parallel(self, role: str, tasks: Iterable[str], max_workers: int = 3) -> list[SubagentResult]:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(self.run, role, task) for task in tasks]
            return [future.result() for future in as_completed(futures)]

    def run_multi_parallel(self, subagent_specs: list[dict[str, str]], max_workers: int = 4) -> list[SubagentResult]:
        """Runs multiple subagents with distinct roles and tasks in parallel."""
        if not subagent_specs:
            return []
        workers = max(1, min(len(subagent_specs), max_workers))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(self.run, spec.get("role", "researcher"), spec.get("task", ""))
                for spec in subagent_specs
            ]
            return [future.result() for future in futures]

