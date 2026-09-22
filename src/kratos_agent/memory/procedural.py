"""Procedural memory store for learned workflows and execution procedures."""
from __future__ import annotations
from typing import Dict, List, Optional

from kratos_agent.memory.models import WorkflowRecord


class ProceduralMemoryStore:
    """Stores and retrieves reusable execution workflows (§24)."""

    def __init__(self) -> None:
        self._workflows: Dict[str, WorkflowRecord] = {}

    def save_workflow(
        self,
        name: str,
        trigger: str,
        steps: List[str],
        application: Optional[str] = None,
    ) -> WorkflowRecord:
        key = name.strip().lower()
        if key in self._workflows:
            wf = self._workflows[key]
            wf.steps = steps
            wf.success_count += 1
            wf.confidence = min(1.0, wf.confidence + 0.05)
            return wf

        wf = WorkflowRecord(
            name=name,
            trigger=trigger,
            steps=steps,
            application=application,
        )
        self._workflows[key] = wf
        return wf

    def get_workflow(self, trigger_or_name: str) -> Optional[WorkflowRecord]:
        clean = trigger_or_name.strip().lower()
        if clean in self._workflows:
            return self._workflows[clean]

        for wf in self._workflows.values():
            if wf.trigger.lower() in clean or clean in wf.trigger.lower() or wf.name.lower() in clean:
                return wf
        return None

    def list_workflows(self) -> List[WorkflowRecord]:
        return list(self._workflows.values())

    def record_outcome(self, name: str, success: bool) -> None:
        key = name.strip().lower()
        wf = self._workflows.get(key)
        if wf:
            if success:
                wf.success_count += 1
                wf.confidence = min(1.0, wf.confidence + 0.05)
            else:
                wf.failure_count += 1
                wf.confidence = max(0.1, wf.confidence - 0.1)
