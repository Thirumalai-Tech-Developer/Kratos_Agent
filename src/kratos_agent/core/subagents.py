"""Isolated subagent orchestration with structured, persisted results."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from typing import Any, Callable, Dict, Iterable, List
import time
import uuid

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
    def __init__(self, run_isolated: Callable[[str, List[ChatMessage]], str]) -> None:
        self.run_isolated = run_isolated

    def run(self, role: str, task: str) -> SubagentResult:
        started, agent_id = time.monotonic(), uuid.uuid4().hex
        prompt = f"You are the Kratos {role} subagent. Return a concise structured report for the parent.\n\nTask: {task}"
        try:
            summary = self.run_isolated(role, [ChatMessage("user", prompt)])
            return SubagentResult(agent_id, role, task, summary, duration_ms=int((time.monotonic() - started) * 1000))
        except Exception as exc:
            return SubagentResult(agent_id, role, task, "", error=str(exc), duration_ms=int((time.monotonic() - started) * 1000))

    def run_parallel(self, role: str, tasks: Iterable[str], max_workers: int = 3) -> List[SubagentResult]:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(self.run, role, task) for task in tasks]
            return [future.result() for future in as_completed(futures)]
