"""Isolated subagent orchestration with structured, persisted results."""
from __future__ import annotations

import time
import threading
import uuid
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass

from .runtime_contracts import ChatMessage, EventKind, RuntimeEvent


def scoped_subagent_event(
    event: RuntimeEvent, identity: dict[str, str], parent_turn_id: str,
) -> RuntimeEvent:
    """Keep child activity separate from parent tokens, tasks, and context usage.

    Model traffic is represented by progress metadata only. The child's final
    report is published by the caller when the isolated run actually ends.
    """
    kind = getattr(event.kind, "value", str(event.kind))
    payload = dict(event.payload or {})
    if kind in {"model.chunk", "model.thinking"}:
        payload = {}
    elif kind == "model.request_assembled":
        payload = {key: payload[key] for key in ("context_usage",) if key in payload}
    elif kind == "model.response":
        payload = {key: payload[key] for key in ("usage", "finish_reason") if key in payload}
    return RuntimeEvent(
        EventKind.SUBAGENT_UPDATED,
        {"subagent": {**identity, "status": "running"},
         "child_turn_id": event.turn_id,
         "activity": {"kind": kind, "payload": payload}},
        parent_turn_id or event.turn_id,
        timestamp=event.timestamp,
    )


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
        self._execution_scope = threading.local()

    @property
    def is_child_thread(self) -> bool:
        return bool(getattr(self._execution_scope, "depth", 0))

    @contextmanager
    def isolated_execution(self):
        """A sibling finishing never changes another worker's nesting guard."""
        previous = getattr(self._execution_scope, "depth", 0)
        self._execution_scope.depth = previous + 1
        try:
            yield
        finally:
            self._execution_scope.depth = previous

    def run(self, role: str, task: str) -> SubagentResult:
        started, agent_id = time.monotonic(), uuid.uuid4().hex
        prompt = (f"You are the Kratos {role} subagent. Return a concise structured report for the parent.\n\n"
                  f"Task: {task}\n\nIsolated task ID: {agent_id}")
        identity = {"agent_id": agent_id, "role": role, "task": task}
        try:
            summary = self.run_isolated(role, [ChatMessage("user", prompt, metadata={"subagent": identity})])
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

