"""Dispute resolution and honest retraction subsystem.

Invariant: When the user contradicts a claimed outcome, Kratos MUST immediately
re-perceive live state and, if the evidence contradicts its own claim, retract
on its own initiative, log a FALSE_COMPLETION, and retry.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from kratos_agent.ccs.assertions import assertion_runner
from kratos_agent.core.evidence import Evidence, OutcomeAssertion

logger = logging.getLogger("kratos.dispute")

DISPUTE_TRIGGERS: dict[str, list[str]] = {
    "en": [
        r"\bno\b.{0,20}\b(didn'?t|not|never)\b",
        r"\bit'?s not\b",
        r"\bnot (playing|open|working|done)\b",
        r"\byou'?re (lying|wrong)\b",
        r"\bcheck again\b",
        r"\blook again\b",
        r"\breally\??$",
        r"\bthat'?s (not|wrong)\b",
        r"\bnothing happened\b",
        r"\bstill\b.{0,20}\b(not|same)\b",
    ],
    "ta": [
        r"இல்லை",
        r"ஆகல",
        r"ஆகவில்லை",
        r"செய்யல",
        r"பாரு",
        r"பார்த்து",
        r"தப்பு",
        r"வரல",
        r"திறக்கல",
        r"பிளே ஆகல",
        r"பொய்",
        r"மறுபடி",
    ],
    "tanglish": [
        r"\billai?\b",
        r"\bilaye?\b",
        r"\billada\b",
        r"\bagaala?\b",
        r"\baagala\b",
        r"\bopen aagala\b",
        r"\bpannala\b",
        r"\bpaaru?\b",
        r"\bpaar athu\b",
        r"\bseyala\b",
        r"\bthappu?\b",
        r"\bvarala\b",
        r"\bthirakkala\b",
        r"\bplay aagala\b",
        r"\bmoodi\b",
        r"\bwrong ah\b",
    ],
}

_COMPILED_TRIGGERS = {
    lang: [re.compile(p, re.IGNORECASE) for p in patterns]
    for lang, patterns in DISPUTE_TRIGGERS.items()
}


def is_dispute(text: str) -> bool:
    """Checks if the user utterance contains a dispute trigger in English, Tamil, or Tanglish."""
    if not text:
        return False
    text = text.strip()
    for lang, patterns in _COMPILED_TRIGGERS.items():
        for pat in patterns:
            if pat.search(text):
                return True
    return False


@dataclass
class DisputeResult:
    reverified: bool
    evidence: Evidence
    wrong: bool
    retraction: str | None
    action: str  # "retrying" | "needs_user" | "explain" | "closed"
    new_task_id: str | None = None
    explanation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "reverified": self.reverified,
            "evidence": self.evidence.to_model_dict(),
            "previous_claim_was_wrong": self.wrong,
            "retraction": self.retraction,
            "action": self.action,
            "new_task_id": self.new_task_id,
            "explanation": self.explanation,
        }


def infer_assertion_from_goal(goal: str) -> OutcomeAssertion:
    """Infers a reasonable outcome assertion when a task did not declare one."""
    g = goal.lower()
    if any(k in g for k in ["play", "video", "youtube", "music"]):
        return OutcomeAssertion(kind="media_playing", params={"min_advance_s": 0.5}, require_samples=2, sample_gap_ms=1500)
    if "chrome" in g or "browser" in g:
        return OutcomeAssertion(kind="process_running", params={"name": "chrome.exe"})
    if "open" in g or "launch" in g:
        return OutcomeAssertion(kind="screen_changed", params={"min_changed_px": 64})
    return OutcomeAssertion(kind="screen_changed", params={"min_changed_px": 32})


def build_retraction(task_claim: str, fresh: Evidence, blockers: list[Any]) -> str:
    """Builds an honest, spoken retraction line."""
    blocker_names = [getattr(b, "name", str(b)) for b in blockers]
    if "youtube_bot_wall" in blocker_names:
        return (
            f"You're right — {task_claim or 'the action'} did not succeed. "
            f"YouTube is showing a sign-in verification wall. No video can play without signing in."
        )
    if fresh.detail:
        return f"You're right, my mistake — {fresh.detail}."
    return "You're right — I said it was completed, but verifying the live screen shows it did not happen."


def retryable(blockers: list[Any], fresh: Evidence) -> bool:
    """Determines whether an autonomous retry is viable."""
    blocker_names = [getattr(b, "name", str(b)) for b in blockers]
    if "youtube_bot_wall" in blocker_names or "os_uac" in blocker_names:
        return False
    return True


async def handle_dispute(
    runtime: Any,
    task_id: str | None = None,
    observation: str = "",
    lang: str = "auto",
) -> DisputeResult:
    """Handles a user dispute with mandatory live re-perception.

    Never replies from memory or acknowledges without observing.
    """
    logger.info("Handling dispute for task_id=%s observation=%s", task_id, observation)

    # 1. Resolve task
    task = None
    if hasattr(runtime, "tasks") and task_id:
        task = runtime.tasks.get(task_id)
    if task is None and hasattr(runtime, "last_terminal_task"):
        task = runtime.last_terminal_task()

    goal = getattr(task, "goal", observation)
    claim = getattr(task, "claim", goal)

    # 2. Re-read live state (never cached)
    assertion = getattr(task, "assertion", None) or infer_assertion_from_goal(goal)
    ccs = getattr(runtime, "ccs", None)
    if ccs is None:
        from kratos_agent.ccs import get_computer_controller
        ccs = get_computer_controller()

    if hasattr(runtime, "verification") and hasattr(runtime.verification, "verify_observable_outcome"):
        fresh = runtime.verification.verify_observable_outcome(assertion, ccs, require_fresh=True)
    else:
        fresh = assertion_runner.run(ccs, assertion)

    # 3. Detect blockers and current context
    from kratos_agent.ccs.perception.blockers import detect_blockers
    blockers = detect_blockers(ccs)

    # 4. Compare against claim
    prior_met = getattr(getattr(task, "evidence", None), "met", False)
    wrong = (not prior_met) or (not fresh.met)

    if wrong:
        # Record false completion audit
        if hasattr(runtime, "audit") and hasattr(runtime.audit, "record"):
            runtime.audit.record(
                kind="FALSE_COMPLETION_CONFIRMED",
                task_id=task_id or "unknown",
                claimed=getattr(task, "evidence", None),
                observed=fresh.to_model_dict(),
                user_observation=observation,
            )

        # Save episodic memory
        if hasattr(runtime, "memory") and hasattr(runtime.memory, "save_tier"):
            runtime.memory.save_tier(
                "episodic",
                key=f"false_completion:{task_id or 'latest'}",
                content=(
                    f"Claimed '{claim}' without valid evidence. User disputed: '{observation}'. "
                    f"Reality: {fresh.detail}. Lesson: assert {assertion.kind} before "
                    f"declaring completion."
                ),
            )

        retraction = build_retraction(claim, fresh, blockers)
        is_retry = retryable(blockers, fresh)

        if is_retry and hasattr(runtime, "retry_task"):
            import inspect
            retry_call = runtime.retry_task(
                task,
                injected_context={
                    "prior_attempt_failed_because": fresh.detail,
                    "blockers": [b.name for b in blockers],
                    "user_says": observation,
                    "hard_rule": f"Do NOT declare completion without passing {assertion.kind}.",
                },
            )
            if inspect.isawaitable(retry_call):
                new_id = await retry_call
            else:
                new_id = retry_call
            return DisputeResult(
                reverified=True,
                evidence=fresh,
                wrong=True,
                retraction=retraction,
                action="retrying",
                new_task_id=new_id,
            )

        action = "needs_user" if not is_retry else "retrying"
        return DisputeResult(
            reverified=True,
            evidence=fresh,
            wrong=True,
            retraction=retraction,
            action=action,
        )

    # 5. The claim was actually right (e.g. window is behind another window or on another monitor)
    primary_win = getattr(task, "primary_window", None)
    if primary_win and hasattr(ccs, "window_action"):
        try:
            ccs.window_action(primary_win, "restore")
            ccs.focus_window(primary_win)
        except Exception as exc:
            logger.debug("Operation error suppressed: %s", exc)

    return DisputeResult(
        reverified=True,
        evidence=fresh,
        wrong=False,
        retraction=None,
        action="explain",
        explanation=(
            f"I checked again just now and it IS {fresh.claim} — {fresh.detail}. "
            "It may have been minimized or behind another window; I have brought it forward."
        ),
    )
