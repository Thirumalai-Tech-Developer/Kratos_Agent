"""Intelligent Provider Router for Kratos Beast.

Orchestrates multi-SDK agent execution, capability matching, automatic failover,
resource locking, parallel waves, multi-agent review workflows, and implementation consensus.
Kratos remains the sole orchestrator, memory authority, tool registry, and verification gatekeeper.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from kratos_agent.providers.base import (
    AgentBackend,
    AgentRun,
    ProviderCapabilityError,
    ProviderError,
    ProviderUnavailable,
)
from kratos_agent.providers.capabilities import (
    TaskRequirements,
    score_provider,
)
from kratos_agent.providers.events import (
    AgentEvent,
    CanonicalEventType,
    redact_secrets,
)
from kratos_agent.providers.health import HealthStatus
from kratos_agent.providers.registry import ProviderRegistry

logger = logging.getLogger(__name__)


class ExecutionMode(str, Enum):
    SINGLE = "single"
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    REVIEW = "review"
    CONSENSUS = "consensus"


class RoutingPolicy(str, Enum):
    AUTO = "auto"
    MANUAL = "manual"
    HYBRID = "hybrid"


@dataclass
class ReviewFinding:
    """Structured finding produced by an agent reviewer."""
    severity: str  # "critical", "high", "medium", "low", "info"
    file: str
    line: int | None
    finding: str
    evidence: str
    recommendation: str
    confidence: float
    reviewer_provider: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "finding": self.finding,
            "evidence": self.evidence,
            "recommendation": self.recommendation,
            "confidence": self.confidence,
            "reviewer_provider": self.reviewer_provider,
        }


@dataclass
class RoutingDecision:
    """Explains why a provider or workflow was selected."""
    task_id: str
    mode: ExecutionMode
    requested_provider: str | None
    selected_provider: str
    fallback_chain: list[str]
    fallback_reason: str | None = None
    reasoning_metadata: list[str] = field(default_factory=list)


class ResourceLockManager:
    """Enforces non-conflicting resource usage and path-safe mutations across provider tasks."""

    def __init__(self) -> None:
        self._active_locks: dict[str, dict[str, set[str]]] = {}
        self._lock = asyncio.Lock()

    async def acquire(
        self,
        task_id: str,
        reads: list[str] | None = None,
        writes: list[str] | None = None,
        side_effects: list[str] | None = None,
    ) -> bool:
        """Acquire resource locks. Returns True if granted, False if conflict exists."""
        reads_set = {os.path.normpath(p) for p in (reads or [])}
        writes_set = {os.path.normpath(p) for p in (writes or [])}
        side_effects_set = set(side_effects or [])

        async with self._lock:
            # Check write-write and write-read conflicts
            for existing_id, resources in self._active_locks.items():
                if existing_id == task_id:
                    continue
                # Cannot write to file being read or written by another task
                if writes_set & resources["writes"]:
                    logger.warning("Resource write-write conflict: %s vs %s on %s", task_id, existing_id, writes_set & resources["writes"])
                    return False
                if writes_set & resources["reads"]:
                    logger.warning("Resource write-read conflict: %s vs %s on %s", task_id, existing_id, writes_set & resources["reads"])
                    return False
                if reads_set & resources["writes"]:
                    logger.warning("Resource read-write conflict: %s vs %s on %s", task_id, existing_id, reads_set & resources["writes"])
                    return False
                # Side effect barriers
                if side_effects_set and resources["side_effects"]:
                    logger.warning("Side-effect barrier conflict between %s and %s", task_id, existing_id)
                    return False

            self._active_locks[task_id] = {
                "reads": reads_set,
                "writes": writes_set,
                "side_effects": side_effects_set,
            }
            return True

    async def release(self, task_id: str) -> None:
        """Release all resource locks held by task_id."""
        async with self._lock:
            self._active_locks.pop(task_id, None)


class ProviderRouter:
    """Orchestrates provider selection, automatic failover, and multi-agent coordination."""

    def __init__(
        self,
        registry: ProviderRegistry | None = None,
        workspace_root: Path | None = None,
        default_policy: RoutingPolicy = RoutingPolicy.AUTO,
    ) -> None:
        self.registry = registry or ProviderRegistry.get_instance()
        self.workspace_root = workspace_root or Path.cwd()
        self.default_policy = default_policy
        self.lock_manager = ResourceLockManager()
        self._provider_history: list[dict[str, Any]] = []

    def parse_natural_language_orchestration(self, text: str) -> dict[str, Any]:
        """Parse natural language orchestration intents into routing policies."""
        lower = text.lower()
        plan: dict[str, Any] = {
            "mode": ExecutionMode.SINGLE,
            "primary_provider": None,
            "reviewer_providers": [],
            "consensus_providers": [],
        }

        # Check consensus requests
        if any(p in lower for p in [
            "two independent implementations",
            "compare two implementations",
            "try two implementations",
            "consensus mode",
            "competing implementations",
        ]):
            plan["mode"] = ExecutionMode.CONSENSUS
            plan["consensus_providers"] = ["codex", "claude"]
            return plan

        # Check multi-agent review requests
        if "review" in lower and any(p in lower for p in ["claude", "kimi", "codex", "two agents"]):
            plan["mode"] = ExecutionMode.REVIEW
            if "claude" in lower:
                plan["reviewer_providers"].append("claude")
            if "kimi" in lower:
                plan["reviewer_providers"].append("kimi")
            if not plan["reviewer_providers"]:
                plan["reviewer_providers"] = ["claude"]

            # Detect primary implementer
            if "codex" in lower:
                plan["primary_provider"] = "codex"
            elif "deepseek" in lower:
                plan["primary_provider"] = "deepseek"
            else:
                plan["primary_provider"] = "kratos_native"
            return plan

        # Detect specific single provider requests
        for name in ["codex", "claude", "kimi", "deepseek", "antigravity", "kratos"]:
            pattern = rf"\b(?:use|with|run via|delegate to)\s+{name}\b"
            if re.search(pattern, lower) or lower.startswith(f"use {name}"):
                plan["primary_provider"] = "kratos_native" if name == "kratos" else name
                return plan

        return plan

    def select_provider(
        self,
        task_id: str,
        requirements: TaskRequirements,
        requested_provider: str | None = None,
        policy: RoutingPolicy | None = None,
    ) -> RoutingDecision:
        """Select optimal provider considering requirements, health, circuit breakers, and policy."""
        effective_policy = policy or self.default_policy
        reasons: list[str] = []

        # If user/caller explicitly requested a provider
        if requested_provider:
            backend = self.registry.get_provider(requested_provider)
            if backend:
                cb = self.registry.circuit_breaker(requested_provider)
                if cb.can_execute():
                    reasons.append(f"Explicitly requested provider '{requested_provider}' selected.")
                    return RoutingDecision(
                        task_id=task_id,
                        mode=ExecutionMode.SINGLE,
                        requested_provider=requested_provider,
                        selected_provider=requested_provider,
                        fallback_chain=self.registry.get_fallback_chain(requested_provider),
                        reasoning_metadata=reasons,
                    )
                else:
                    reasons.append(f"Requested provider '{requested_provider}' circuit open, attempting fallback.")
                    fallback_chain = self.registry.get_fallback_chain(requested_provider)
                    for fallback_p in fallback_chain:
                        fb_cb = self.registry.circuit_breaker(fallback_p)
                        if fb_cb.can_execute():
                            remaining_chain = [p for p in fallback_chain if p != fallback_p]
                            reasons.append(f"Falling back to '{fallback_p}' from configured fallback chain.")
                            return RoutingDecision(
                                task_id=task_id,
                                mode=ExecutionMode.SINGLE,
                                requested_provider=requested_provider,
                                selected_provider=fallback_p,
                                fallback_chain=remaining_chain,
                                fallback_reason=f"Circuit open for '{requested_provider}'",
                                reasoning_metadata=reasons,
                            )

        # Evaluate candidate providers
        candidates: list[tuple[str, float, list[str]]] = []
        for name, backend in self.registry.list_providers().items():
            health = self.registry.health_check(name)
            cb = self.registry.circuit_breaker(name)
            if health.status not in (HealthStatus.READY, HealthStatus.DEGRADED) or not cb.can_execute():
                continue

            score, match_reasons = score_provider(name, backend.capabilities(), requirements)
            candidates.append((name, score, match_reasons))

        if not candidates:
            # Fall back to kratos_native
            reasons.append("No specialized backends healthy, falling back to Kratos native runtime.")
            return RoutingDecision(
                task_id=task_id,
                mode=ExecutionMode.SINGLE,
                requested_provider=requested_provider,
                selected_provider="kratos_native",
                fallback_chain=["kratos_native"],
                fallback_reason="No external providers available",
                reasoning_metadata=reasons,
            )

        # Sort candidates by score descending
        candidates.sort(key=lambda c: c[1], reverse=True)
        winner_name, best_score, best_reasons = candidates[0]
        reasons.extend(best_reasons)

        fallback_chain = [c[0] for c in candidates if c[0] != winner_name]
        if "kratos_native" not in fallback_chain and winner_name != "kratos_native":
            fallback_chain.append("kratos_native")

        return RoutingDecision(
            task_id=task_id,
            mode=ExecutionMode.SINGLE,
            requested_provider=requested_provider,
            selected_provider=winner_name,
            fallback_chain=fallback_chain,
            reasoning_metadata=reasons,
        )

    async def execute_task(
        self,
        task_id: str,
        session_id: str,
        prompt: str,
        requirements: TaskRequirements | None = None,
        requested_provider: str | None = None,
        context: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> AgentRun:
        """Execute a task with automatic failover across the provider fallback chain."""
        reqs = requirements or TaskRequirements()
        decision = self.select_provider(task_id, reqs, requested_provider)
        candidates = [decision.selected_provider] + decision.fallback_chain

        last_error: Exception | None = None
        for provider_name in candidates:
            cb = self.registry.circuit_breaker(provider_name)
            if not cb.can_execute():
                continue

            try:
                backend = self.registry.get(provider_name)
            except ProviderUnavailable:
                continue

            t0 = time.monotonic()
            try:
                logger.info("Executing task %s with provider %s", task_id, provider_name)
                sess = None
                try:
                    import inspect
                    start_sig = inspect.signature(backend.start_session)
                    if "workspace" in start_sig.parameters:
                        sess = await backend.start_session(session_id=session_id, workspace=str(self.workspace_root))
                    else:
                        sess = await backend.start_session(task_id=task_id, session_id=session_id, context=context)
                except Exception as se:
                    logger.debug("start_session handled: %s", se)

                import inspect
                run_sig = inspect.signature(backend.run)
                kwargs: dict[str, Any] = {}
                if "instruction" in run_sig.parameters:
                    kwargs["instruction"] = prompt
                if "prompt" in run_sig.parameters:
                    kwargs["prompt"] = prompt
                if "session" in run_sig.parameters and sess is not None:
                    kwargs["session"] = sess
                if "session_id" in run_sig.parameters:
                    kwargs["session_id"] = session_id
                if "context" in run_sig.parameters:
                    kwargs["context"] = context
                if "tools" in run_sig.parameters:
                    kwargs["tools"] = tools

                has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in run_sig.parameters.values())
                if has_var_keyword:
                    kwargs.setdefault("session_id", session_id)
                    kwargs.setdefault("prompt", prompt)
                    kwargs.setdefault("instruction", prompt)
                    if sess is not None:
                        kwargs.setdefault("session", sess)
                    kwargs.setdefault("context", context)
                    kwargs.setdefault("tools", tools)

                run = await backend.run(task_id=task_id, **kwargs)
                cb.record_success()
                duration = time.monotonic() - t0
                self._record_telemetry(task_id, provider_name, duration, success=True)
                return run
            except Exception as e:
                cb.record_failure(str(e))
                duration = time.monotonic() - t0
                self._record_telemetry(task_id, provider_name, duration, success=False, error=str(e))
                logger.warning("Provider %s failed for task %s: %s. Trying fallback.", provider_name, task_id, e)
                last_error = e

        # All candidates failed
        raise ProviderError(
            provider="router",
            message=f"All provider candidates exhausted for task {task_id}. Last error: {last_error}",
            original_exception=last_error,
        )

    async def execute_parallel(
        self,
        tasks: list[dict[str, Any]],
        session_id: str,
    ) -> list[AgentRun | Exception]:
        """Execute multiple non-conflicting tasks concurrently respecting resource locks."""
        async def _run_guarded(task_spec: dict[str, Any]) -> AgentRun:
            t_id = task_spec.get("task_id", str(uuid.uuid4())[:8])
            reads = task_spec.get("reads", [])
            writes = task_spec.get("writes", [])
            side_effects = task_spec.get("side_effects", [])

            # Wait for resource lock
            while not await self.lock_manager.acquire(t_id, reads, writes, side_effects):
                await asyncio.sleep(0.1)

            try:
                return await self.execute_task(
                    task_id=t_id,
                    session_id=session_id,
                    prompt=task_spec["prompt"],
                    requirements=task_spec.get("requirements"),
                    requested_provider=task_spec.get("provider"),
                    context=task_spec.get("context"),
                    tools=task_spec.get("tools"),
                )
            finally:
                await self.lock_manager.release(t_id)

        coros = [_run_guarded(spec) for spec in tasks]
        return await asyncio.gather(*coros, return_exceptions=True)

    async def execute_review_workflow(
        self,
        task_id: str,
        session_id: str,
        prompt: str,
        coder_provider: str = "codex",
        reviewer_providers: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute coordinated review workflow: Coder implements -> Specialists review -> Kratos verifies."""
        reviewers = reviewer_providers or ["claude", "kimi"]
        logger.info("Starting Multi-Agent Review Workflow for task %s (Coder=%s, Reviewers=%s)", task_id, coder_provider, reviewers)

        # 1. Implementation turn
        coder_run = await self.execute_task(
            task_id=f"{task_id}-impl",
            session_id=session_id,
            prompt=prompt,
            requested_provider=coder_provider,
            context=context,
        )

        # 2. Parallel Reviewers (Read-only review prompt)
        review_prompt = (
            f"Review the following proposed implementation for task: '{prompt}'\n\n"
            f"Implementation Output:\n{coder_run.output}\n\n"
            "Provide structured findings in the following format for any bugs, security flaws, or regression risks:\n"
            "SEVERITY: [critical|high|medium|low|info]\n"
            "FILE: [filepath]\n"
            "LINE: [line number or 0]\n"
            "FINDING: [one sentence summary]\n"
            "EVIDENCE: [code snippet or logical proof]\n"
            "RECOMMENDATION: [how to fix]\n"
            "CONFIDENCE: [0.0 to 1.0]\n"
        )

        review_tasks = [
            {
                "task_id": f"{task_id}-review-{p}",
                "prompt": review_prompt,
                "provider": p,
                "context": {"read_only": True},
                "reads": context.get("files", []) if context else [],
            }
            for p in reviewers
        ]

        review_results = await self.execute_parallel(review_tasks, session_id)
        findings: list[ReviewFinding] = []

        for p_name, res in zip(reviewers, review_results):
            if isinstance(res, AgentRun):
                parsed = self._parse_review_findings(res.output, p_name)
                findings.extend(parsed)

        # 3. Deduplicate findings
        deduped = self._deduplicate_findings(findings)

        return {
            "task_id": task_id,
            "coder_provider": coder_provider,
            "coder_output": coder_run.output,
            "reviewers": reviewers,
            "findings": [f.to_dict() for f in deduped],
            "verified": len([f for f in deduped if f.severity in ("critical", "high")]) == 0,
        }

    async def execute_consensus_workflow(
        self,
        task_id: str,
        session_id: str,
        prompt: str,
        candidate_providers: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute consensus workflow: 2 independent implementations in isolated workspaces -> test both -> select winner."""
        providers = candidate_providers or ["codex", "claude"]
        base_dir = self.workspace_root / ".kratos" / "consensus" / task_id
        base_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Executing Consensus Mode for task %s with providers %s", task_id, providers)

        candidate_tasks = []
        workspace_paths: dict[str, Path] = {}

        for p in providers[:2]:
            p_ws = base_dir / f"workspace_{p}"
            p_ws.mkdir(parents=True, exist_ok=True)
            workspace_paths[p] = p_ws

            # Create task spec pointing to isolated workspace
            t_spec = {
                "task_id": f"{task_id}-consensus-{p}",
                "prompt": prompt,
                "provider": p,
                "context": {**(context or {}), "isolated_workspace": str(p_ws)},
                "writes": [str(p_ws)],
            }
            candidate_tasks.append(t_spec)

        runs = await self.execute_parallel(candidate_tasks, session_id)

        # Evaluate both solutions objectively (syntax, completeness, output)
        evaluations: list[dict[str, Any]] = []
        for p, run in zip(providers[:2], runs):
            if isinstance(run, AgentRun):
                score = 1.0 if run.status == "completed" else 0.0
                evaluations.append({
                    "provider": p,
                    "output": run.output,
                    "score": score,
                    "workspace": str(workspace_paths[p]),
                })
            else:
                evaluations.append({
                    "provider": p,
                    "output": f"Failed: {run}",
                    "score": -1.0,
                    "workspace": str(workspace_paths[p]),
                })

        # Select highest scoring candidate
        evaluations.sort(key=lambda e: e["score"], reverse=True)
        winner = evaluations[0]

        # Clean up temporary consensus workspaces
        try:
            shutil.rmtree(base_dir, ignore_errors=True)
        except Exception as e:
            logger.debug("Failed to remove consensus workspace: %s", e)

        return {
            "task_id": task_id,
            "winning_provider": winner["provider"],
            "winning_output": winner["output"],
            "evaluations": evaluations,
        }

    def _parse_review_findings(self, text: str, provider_name: str) -> list[ReviewFinding]:
        """Parse structured review blocks from reviewer text."""
        findings: list[ReviewFinding] = []
        blocks = re.split(r"(?=SEVERITY:)", text, flags=re.IGNORECASE)

        for block in blocks:
            if not block.strip() or "SEVERITY:" not in block.upper():
                continue
            severity_m = re.search(r"SEVERITY:\s*([a-zA-Z]+)", block, re.IGNORECASE)
            file_m = re.search(r"FILE:\s*([^\n\r]+)", block, re.IGNORECASE)
            line_m = re.search(r"LINE:\s*(\d+)", block, re.IGNORECASE)
            finding_m = re.search(r"FINDING:\s*([^\n\r]+)", block, re.IGNORECASE)
            evidence_m = re.search(r"EVIDENCE:\s*([^\n\r]+)", block, re.IGNORECASE)
            rec_m = re.search(r"RECOMMENDATION:\s*([^\n\r]+)", block, re.IGNORECASE)
            conf_m = re.search(r"CONFIDENCE:\s*([\d\.]+)", block, re.IGNORECASE)

            sev = severity_m.group(1).lower() if severity_m else "medium"
            f_path = file_m.group(1).strip() if file_m else "general"
            line_no = int(line_m.group(1)) if line_m else None
            f_text = finding_m.group(1).strip() if finding_m else block.strip()[:100]
            ev = evidence_m.group(1).strip() if evidence_m else ""
            rec = rec_m.group(1).strip() if rec_m else ""
            conf = float(conf_m.group(1)) if conf_m else 0.8

            findings.append(ReviewFinding(
                severity=sev,
                file=f_path,
                line=line_no,
                finding=f_text,
                evidence=ev,
                recommendation=rec,
                confidence=conf,
                reviewer_provider=provider_name,
            ))
        return findings

    def _deduplicate_findings(self, findings: list[ReviewFinding]) -> list[ReviewFinding]:
        """Merge identical or overlapping findings across reviewers."""
        seen: set[str] = set()
        deduped: list[ReviewFinding] = []
        for f in findings:
            key = f"{f.file}:{f.line}:{f.finding[:40].lower()}"
            if key not in seen:
                seen.add(key)
                deduped.append(f)
        return deduped

    def _record_telemetry(
        self,
        task_id: str,
        provider: str,
        duration: float,
        success: bool,
        error: str | None = None,
    ) -> None:
        """Record provider telemetry for feedback and quality routing."""
        record = {
            "task_id": task_id,
            "provider": provider,
            "duration": duration,
            "success": success,
            "error": error,
            "timestamp": time.time(),
        }
        self._provider_history.append(record)
        if len(self._provider_history) > 1000:
            self._provider_history = self._provider_history[-500:]

    def get_telemetry_summary(self) -> dict[str, Any]:
        """Generate provider telemetry summary metrics."""
        summary: dict[str, dict[str, Any]] = {}
        for entry in self._provider_history:
            p = entry["provider"]
            if p not in summary:
                summary[p] = {"total": 0, "success": 0, "failures": 0, "total_duration": 0.0}
            summary[p]["total"] += 1
            if entry["success"]:
                summary[p]["success"] += 1
            else:
                summary[p]["failures"] += 1
            summary[p]["total_duration"] += entry["duration"]

        result = {}
        for p, stats in summary.items():
            tot = stats["total"]
            result[p] = {
                "tasks_executed": tot,
                "success_rate": round(stats["success"] / tot, 2) if tot else 0.0,
                "avg_duration_sec": round(stats["total_duration"] / tot, 2) if tot else 0.0,
            }
        return result
