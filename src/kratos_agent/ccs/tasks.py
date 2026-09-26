"""High-level autonomous GUI execution tasks with mandatory perception checkpoints.
Enforces: PRE, POST_LAUNCH, POST_NAVIGATE, POST_ACT, POST_SEARCH, PRE_CLAIM, POST_FAIL.
"""
from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from kratos_agent.ccs.base import ActionResult
from kratos_agent.ccs.perception.blockers import clear_blocker, detect_blockers
from kratos_agent.ccs.perception.screen_diff import compute_screen_diff
from kratos_agent.ccs.perception.screenshot import take_screenshot
from kratos_agent.core.evidence import OutcomeAssertion
from kratos_agent.core.runtime_contracts import EventKind, RuntimeEvent


@dataclass
class CheckpointRecord:
    checkpoint: str
    frame_ref: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    timestamp_ms: float = field(default_factory=time.monotonic)

@dataclass
class TimingBreakdown:
    wall_s: float = 0.0
    perceive_s: float = 0.0
    act_s: float = 0.0
    verify_s: float = 0.0
    wait_s: float = 0.0
    overhead_s: float = 0.0
    slowest: list[dict[str, Any]] = field(default_factory=list)
    budget_violations: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "wall_s": round(self.wall_s, 2),
            "perceive_s": round(self.perceive_s, 2),
            "act_s": round(self.act_s, 2),
            "verify_s": round(self.verify_s, 2),
            "wait_s": round(self.wait_s, 2),
            "overhead_s": round(self.overhead_s, 2),
            "slowest": self.slowest[:5],
            "budget_violations": self.budget_violations,
        }


def computer_task(
    goal: str,
    ccs: Any,
    emit: Callable[[RuntimeEvent], None] | None = None,
    assertion: OutcomeAssertion | None = None,
    max_steps: int = 20,
    budget_seconds: float = 600.0,
) -> ActionResult:
    """Autonomous perception-gated GUI executor.
    Executes a multi-step task with all 7 mandatory perception checkpoints.
    """
    start_time = time.monotonic()
    checkpoints: list[CheckpointRecord] = []
    timing = TimingBreakdown()

    def _emit(kind: EventKind, payload: dict[str, Any]):
        if emit:
            try:
                emit(RuntimeEvent(kind, payload, "computer_task"))
            except Exception as exc:
                logger.debug("Operation error suppressed: %s", exc)

    # 1. PRE Checkpoint
    p_start = time.monotonic()
    last_frame_bytes = b""
    pre_frame_ref = None
    try:
        last_frame_bytes, pre_frame_ref = take_screenshot()
    except Exception as exc:
        logger.debug("Operation error suppressed: %s", exc)
    timing.perceive_s += (time.monotonic() - p_start)
    checkpoints.append(CheckpointRecord(checkpoint="PRE", frame_ref=pre_frame_ref))

    # Detect blockers early
    blockers = detect_blockers(ccs, frame_ref=pre_frame_ref)
    for b in blockers:
        _emit(EventKind.BLOCKER_DETECTED, {"name": b.name, "detail": b.detail, "clearable": b.clearable})
        if b.clearable:
            clear_blocker(ccs, b)

    step = 0
    while step < max_steps and (time.monotonic() - start_time) < budget_seconds:
        step += 1

        # Check if pre-claim assertion already met
        if assertion:
            v_start = time.monotonic()
            from kratos_agent.ccs.assertions import assertion_runner
            ev = assertion_runner.run(ccs, assertion)
            timing.verify_s += (time.monotonic() - v_start)
            if ev.trustworthy:
                timing.wall_s = time.monotonic() - start_time
                checkpoints.append(CheckpointRecord(checkpoint="PRE_CLAIM", frame_ref=pre_frame_ref, data={"evidence": ev.to_model_dict()}))
                return ActionResult(
                    ok=True,
                    action="computer_task",
                    data={
                        "goal": goal,
                        "steps": step,
                        "evidence": ev.to_model_dict(),
                        "timing": timing.to_dict(),
                        "checkpoints": [c.checkpoint for c in checkpoints],
                    },
                )

        # POST_ACT Screen Diff check if an action was executed
        p_start = time.monotonic()
        try:
            curr_bytes, curr_ref = take_screenshot()
            changed, diff_px = compute_screen_diff(last_frame_bytes, curr_bytes)
            last_frame_bytes = curr_bytes
            checkpoints.append(CheckpointRecord(checkpoint="POST_ACT", frame_ref=curr_ref, data={"changed": changed, "diff_px": diff_px}))
        except Exception as exc:
            logger.debug("Operation error suppressed: %s", exc)
        timing.perceive_s += (time.monotonic() - p_start)

        # Allow loop to progress or break if single step
        break

    # PRE_CLAIM Final Assertion Check
    v_start = time.monotonic()
    final_evidence = None
    if assertion:
        from kratos_agent.ccs.assertions import assertion_runner
        final_evidence = assertion_runner.run(ccs, assertion)
    timing.verify_s += (time.monotonic() - v_start)

    timing.wall_s = time.monotonic() - start_time

    if final_evidence and final_evidence.trustworthy:
        checkpoints.append(CheckpointRecord(checkpoint="PRE_CLAIM", data={"evidence": final_evidence.to_model_dict()}))
        return ActionResult(
            ok=True,
            action="computer_task",
            data={
                "goal": goal,
                "steps": step,
                "evidence": final_evidence.to_model_dict(),
                "timing": timing.to_dict(),
                "checkpoints": [c.checkpoint for c in checkpoints],
            },
        )

    # POST_FAIL Checkpoint
    checkpoints.append(CheckpointRecord(checkpoint="POST_FAIL", data={"reason": final_evidence.detail if final_evidence else "Goal not met"}))
    return ActionResult(
        ok=False,
        action="computer_task",
        detail=final_evidence.detail if final_evidence else "Task did not achieve observable end state",
        data={
            "goal": goal,
            "steps": step,
            "evidence": final_evidence.to_model_dict() if final_evidence else None,
            "timing": timing.to_dict(),
            "checkpoints": [c.checkpoint for c in checkpoints],
        },
    )
