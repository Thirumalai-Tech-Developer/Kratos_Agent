"""Bridge from Gemini semantic missions to Master/Slave execution."""
from __future__ import annotations

import logging
import asyncio
from typing import Any, Dict, Optional

from kratos_agent.diagnostics.errors import error_from_exception
from kratos_agent.master.supervisor import get_master_supervisor
from kratos_agent.slave.executor import get_slave_executor
from .events import LiveState, LiveStatusHub

logger = logging.getLogger(__name__)


class KratosBridge:
    def __init__(self, runtime: Optional[Any] = None, status_hub: Optional[LiveStatusHub] = None) -> None:
        if runtime is None:
            from kratos_agent.main import runtime as default_runtime
            runtime = default_runtime
        self.runtime = runtime
        self.status_hub = status_hub
        self.supervisor = get_master_supervisor()
        self.slave_executor = get_slave_executor()
        self.slave_executor.runtime = self.runtime
        try:
            asyncio.get_running_loop()
            self.slave_executor.start()
        except RuntimeError:
            pass

    def is_busy(self) -> bool:
        return self.supervisor.is_busy()

    async def submit_task(
        self,
        task_description: str,
        visual_context: Optional[str] = None,
        action: str = "generic_task",
        parameters: Optional[Dict[str, Any]] = None,
        constraints: Optional[Dict[str, Any]] = None,
        expected_result: Optional[Dict[str, Any]] = None,
        priority: str = "normal",
        timeout: float = 60.0,
        force: bool = False,
        request_id: str = "",
        turn_id: str = "",
        tool_call_id: str = "",
        wait_for_result: bool = False,
    ) -> Dict[str, Any]:
        from kratos_agent.live.echo_guard import get_echo_guard
        from kratos_agent.core.task_deduplicator import get_task_deduplicator

        if get_echo_guard().should_suppress_mic():
            return {"status": "echo_suppressed", "message": "Ignored microphone echo during or immediately after TTS playback."}

        if get_task_deduplicator().is_duplicate(task_description):
            return {"status": "duplicate_suppressed", "message": "Duplicate request suppressed by request deduplication."}

        objective = str(task_description or "").strip()
        if not objective:
            return {"status": "error", "error_type": "validation_error", "message": "Mission objective is empty."}

        params = dict(parameters or {})
        constrs = dict(constraints or {})
        exp_res = dict(expected_result or {})
        capability = str(action or "").strip()

        # The bridge can be constructed before LiveRuntime's background event loop.
        # Start the Slave when a real mission is submitted so commands are consumable.
        if not self.slave_executor._running:
            self.slave_executor.start()

        # Transport boundary only. Gemini supplies semantic intent; Master owns discovery.
        if self.status_hub:
            self.status_hub.update(current_state=LiveState.EXECUTING)

        try:
            result = await self.supervisor.submit_delegated_task(
                objective=objective,
                action=capability,
                parameters=params,
                constraints=constrs,
                expected_result=exp_res,
                priority=priority,
                timeout=(max(timeout, 600.0) if (wait_for_result and capability in {"", "generic_task", "auto", "null", "none"}) else timeout),
                context={
                    "visual_context": visual_context,
                    "request_id": request_id,
                    "turn_id": turn_id,
                    "tool_call_id": tool_call_id,
                },
                force=force,
                wait_for_result=wait_for_result,
            )
        except Exception as exc:
            error = error_from_exception(
                exc,
                component="KratosBridge",
                stage="task_submission",
                request_id=request_id or None,
                retryable=True,
                recovery_action="Retry submission or inspect Master/Slave status.",
            )
            logger.exception("[LiveBridge] task submission failed")
            if self.status_hub:
                self.status_hub.report_error("bridge", error.user_message)
            return {"status": "failed", "accepted": False, "error": error.to_dict()}

        if self.status_hub and result.get("task_id"):
            if wait_for_result and result.get("status") in {"success", "failed", "partial", "cancelled"}:
                self.status_hub.update(active_task_id=None)
            else:
                self.status_hub.update(active_task_id=result["task_id"])
        if self.status_hub and result.get("status") in {"failed", "partial", "error"}:
            detail = result.get("error") or {}
            if isinstance(detail, dict):
                message = detail.get("user_message") or detail.get("message") or result.get("message")
                component = detail.get("component") or "slave"
            else:
                message = str(detail)
                component = "slave"
            self.status_hub.report_error(component, str(message or "Mission failed without a diagnostic."))
        return {
            **result,
            "capability": result.get("capability") or capability or "generic_task",
        }

    async def cancel_active_task(self) -> Dict[str, Any]:
        result = await self.supervisor.cancel_active_task()
        if hasattr(self.runtime, "cancel"):
            self.runtime.cancel()
        if self.status_hub:
            self.status_hub.update(active_task_id=None, current_state=LiveState.IDLE)
        return result

    def get_status(self, task_id: Optional[str] = None) -> Dict[str, Any]:
        status = self.supervisor.get_status(task_id)
        if status.get("last_error"):
            status["task_error"] = status["last_error"]
        if self.status_hub:
            live = self.status_hub.status
            status.update({
                "live_connected": live.gemini_connected,
                "live_health": live.live_health,
                "last_error": live.last_error or status.get("last_error"),
                "last_error_component": live.last_error_component or status.get("error_component"),
            })
        error = status.get("task_error") or status.get("last_error")
        if isinstance(error, dict):
            message = error.get("user_message") or error.get("message")
            component = error.get("component") or status.get("last_error_component") or "agent"
            stage = error.get("stage") or status.get("current_stage") or "execution"
            recovery = error.get("recovery_action")
        else:
            message = error
            component = status.get("last_error_component") or "agent"
            stage = status.get("current_stage") or "execution"
            recovery = None
        if message:
            summary = f"Last task failed in {component} during {stage}: {message}"
            if recovery:
                summary += f" Recovery: {recovery}"
            status["diagnostic_summary"] = summary
        return status
