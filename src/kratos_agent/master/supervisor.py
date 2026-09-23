"""Master lifecycle supervisor for structured Gemini missions."""
from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from typing import Any, Callable, Dict, Optional

from kratos_agent.diagnostics.errors import error_from_exception
from kratos_agent.orchestrator.mission import get_mission_coordinator
from kratos_agent.orchestrator.state import MissionState
from kratos_agent.capabilities.discovery import discover_capabilities
from .protocol import MasterCommand, SlaveAck, SlaveResult, get_command_bus

logger = logging.getLogger(__name__)


class MasterSupervisor:
    def __init__(self, session_id: Optional[str] = None) -> None:
        self.session_id = session_id or f"LIVE-{uuid.uuid4().hex[:6].upper()}"
        self.command_bus = get_command_bus()
        self.active_task_id: Optional[str] = None
        self.active_command_id: Optional[str] = None
        self.active_objective: Optional[str] = None
        self.last_result: Optional[Dict[str, Any]] = None
        self.last_error: Optional[Dict[str, Any]] = None
        self.last_task_id: Optional[str] = None
        self.last_started_at: Optional[float] = None
        self.last_completed_at: Optional[float] = None
        self._lock = threading.Lock()
        self._on_speech_feedback: Optional[Callable[[str], None]] = None

    def set_speech_callback(self, cb: Callable[[str], None]) -> None:
        self._on_speech_feedback = cb

    def is_busy(self) -> bool:
        with self._lock:
            return self.active_task_id is not None

    async def submit_delegated_task(
        self,
        objective: str,
        action: str = "generic_task",
        parameters: Optional[Dict[str, Any]] = None,
        constraints: Optional[Dict[str, Any]] = None,
        expected_result: Optional[Dict[str, Any]] = None,
        priority: str = "normal",
        timeout: float = 60.0,
        context: Optional[Dict[str, Any]] = None,
        force: bool = False,
        wait_for_result: bool = False,
    ) -> Dict[str, Any]:
        with self._lock:
            if self.active_task_id is not None and not force and priority.lower() != "cancel":
                return {
                    "status": "busy",
                    "accepted": False,
                    "message": f"Another mission is active: {self.active_objective or self.active_task_id}.",
                    "active_task_id": self.active_task_id,
                }

        context_data = dict(context or {})
        requested_capability = str(action or "").strip()
        candidates: list[Dict[str, Any]] = []
        if requested_capability in {"", "generic_task", "auto", "null", "none"}:
            candidates = discover_capabilities(objective, limit=5)
            requested_capability = (
                str(candidates[0].get("capability_id") or "generic_task")
                if candidates else "generic_task"
            )
        context_data["capability_candidates"] = candidates
        context_data.setdefault("request_id", f"REQ-{uuid.uuid4().hex[:10].upper()}")

        cmd = MasterCommand.create(
            objective=objective,
            action=requested_capability,
            parameters=parameters or {},
            constraints=constraints or {},
            expected_result=expected_result or {},
            context=context_data,
            priority=priority,
            timeout=timeout,
            session_id=self.session_id,
            request_id=context_data.get("request_id"),
            turn_id=context_data.get("turn_id"),
            action_id=context_data.get("action_id"),
            tool_call_id=context_data.get("tool_call_id"),
        )

        mission = get_mission_coordinator().create(
            goal=objective,
            capability=requested_capability,
            arguments=parameters or {},
            constraints=constraints or {},
            expected_result=expected_result or {},
            priority=priority,
            request_id=(context or {}).get("request_id") or None,
            task_id=cmd.task_id,
        )
        mission.task_id = cmd.task_id
        mission.transition(MissionState.ANALYZING, message="Structured mission accepted from Gemini.")
        mission.transition(MissionState.PLANNING, message="Master created execution plan.")
        mission.transition(MissionState.READY, message="Master accepted mission for Slave.")

        with self._lock:
            self.active_task_id = cmd.task_id
            self.active_command_id = cmd.command_id
            self.active_objective = objective
            self.last_task_id = cmd.task_id
            self.last_started_at = time.time()
            self.last_result = {
                "status": "started",
                "task_id": cmd.task_id,
                "capability": requested_capability,
                "capability_candidates": candidates,
            }
            self.last_error = None

        mission.transition(MissionState.EXECUTING, message="Slave execution started.")
        ack_fut, result_fut = await self.command_bus.send_command(cmd)
        try:
            ack: SlaveAck = await asyncio.wait_for(ack_fut, timeout=5.0)
        except asyncio.TimeoutError:
            ack = SlaveAck(command_id=cmd.command_id, task_id=cmd.task_id, accepted=True, status="accepted")

        if not ack.accepted:
            with self._lock:
                self.last_result = {
                    "status": "rejected",
                    "task_id": cmd.task_id,
                    "capability": action,
                    "message": ack.message or "Slave rejected the mission.",
                }
                self.active_task_id = None
                self.active_command_id = None
                self.active_objective = None
            get_mission_coordinator().update_result(cmd.task_id, self.last_result)
            return self.last_result

        result_task = asyncio.create_task(
            self._await_result(cmd, result_fut, emit_speech=not wait_for_result)
        )
        if wait_for_result:
            result_dict = await result_task
            return {
                **result_dict,
                "accepted": True,
                "task_id": cmd.task_id,
                "command_id": cmd.command_id,
                "capability": requested_capability,
                "capability_candidates": candidates,
            }

        return {
            "status": "started",
            "accepted": True,
            "task_id": cmd.task_id,
            "command_id": cmd.command_id,
            "capability": requested_capability,
            "capability_candidates": candidates,
            "summary": f"Mission accepted for Slave execution: {objective}",
        }

    async def _await_result(
        self,
        cmd: MasterCommand,
        result_fut: asyncio.Future[SlaveResult],
        *,
        emit_speech: bool = True,
    ) -> Dict[str, Any]:
        try:
            result = await asyncio.wait_for(result_fut, timeout=cmd.timeout)
            result_dict = result.to_dict()
            mission = get_mission_coordinator().get(cmd.task_id)
            if mission:
                mission.transition(
                    MissionState.VERIFYING,
                    message="Master received Slave result; verifying evidence.",
                )
            with self._lock:
                self.last_result = result_dict
                self.last_completed_at = time.time()
                self.last_error = result.error or None
            get_mission_coordinator().update_result(cmd.task_id, result_dict)

            summary = self.format_response_for_master(result)
            if emit_speech and self._on_speech_feedback and summary:
                self._on_speech_feedback(summary)
            return result_dict
        except asyncio.TimeoutError as exc:
            error = error_from_exception(
                exc,
                component="MasterSupervisor",
                stage="execution_timeout",
                task_id=cmd.task_id,
                request_id=cmd.request_id or None,
                retryable=True,
                recovery_action="Inspect current task state and retry after fresh observation.",
                user_message=f"Mission {cmd.task_id} timed out before verified completion.",
            ).to_dict()
            result_dict = {
                "status": "failed",
                "accepted": True,
                "task_id": cmd.task_id,
                "command_id": cmd.command_id,
                "capability": cmd.action,
                "error": error,
            }
            with self._lock:
                self.last_error = error
                self.last_result = result_dict
                self.last_completed_at = time.time()
            get_mission_coordinator().update_result(cmd.task_id, result_dict)
            if emit_speech and self._on_speech_feedback:
                self._on_speech_feedback(error["user_message"])
            return result_dict
        except Exception as exc:
            error = error_from_exception(
                exc,
                component="MasterSupervisor",
                stage="await_result",
                task_id=cmd.task_id,
                request_id=cmd.request_id or None,
                retryable=True,
                recovery_action="Inspect Slave status and retry the mission.",
                user_message=f"Mission execution failed in Master while waiting for the Slave: {type(exc).__name__}.",
            ).to_dict()
            result_dict = {
                "status": "failed",
                "accepted": True,
                "task_id": cmd.task_id,
                "command_id": cmd.command_id,
                "capability": cmd.action,
                "error": error,
            }
            with self._lock:
                self.last_error = error
                self.last_result = result_dict
                self.last_completed_at = time.time()
            get_mission_coordinator().update_result(cmd.task_id, result_dict)
            if emit_speech and self._on_speech_feedback:
                self._on_speech_feedback(error["user_message"])
            return result_dict
        finally:
            with self._lock:
                if self.active_command_id == cmd.command_id:
                    self.active_task_id = None
                    self.active_command_id = None
                    self.active_objective = None

    async def cancel_active_task(self, reason: str = "User cancelled") -> Dict[str, Any]:
        with self._lock:
            task_id = self.active_task_id
        if not task_id:
            return {"status": "idle", "message": "No active mission."}

        await self.command_bus.cancel_task(task_id, reason)
        with self._lock:
            self.last_result = {"status": "cancelled", "task_id": task_id, "message": reason}
            self.last_completed_at = time.time()
            self.active_task_id = None
            self.active_command_id = None
            self.active_objective = None
        get_mission_coordinator().update_result(task_id, self.last_result)
        return self.last_result

    def get_status(self, task_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            active_id = self.active_task_id
            objective = self.active_objective
            result = dict(self.last_result or {})
            error = dict(self.last_error or {}) if self.last_error else None

        selected_task = task_id or active_id or result.get("task_id") or self.last_task_id
        mission = get_mission_coordinator().get(selected_task) if selected_task else None
        return {
            "status": "running" if active_id else (result.get("status") or "idle"),
            "state": (mission.state_machine.state.value if mission and mission.state_machine else None),
            "current_state": (mission.state_machine.state.value if mission and mission.state_machine else None),
            "task_id": selected_task,
            "active_task_id": active_id,
            "mission": mission.goal if mission else objective,
            "current_stage": (mission.state_machine.state.value if mission and mission.state_machine else None),
            "current_capability": mission.capability if mission else result.get("capability"),
            "execution_backend": (result.get("evidence") or {}).get("backend"),
            "last_event": (mission.state_machine.history[-1] if mission and mission.state_machine and mission.state_machine.history else None),
            "last_result": result or None,
            "last_error": error,
            "error_component": error.get("component") if error else None,
            "retryable": bool(error.get("retryable")) if error else False,
            "recovery_attempt": (error.get("recovery_action") if error else None),
            "is_busy": bool(active_id),
            "active_task_desc": objective,
        }

    def format_response_for_master(self, result: SlaveResult) -> str:
        if result.is_success():
            if result.state == "VIDEO_PLAYING":
                return "Done — the video is playing."
            if result.state == "SEARCH_RESULTS":
                return "Done — search results are displayed."
            if result.state == "APPLICATION_OPENED":
                return "Done — the application is open and verified."
            if result.evidence.get("message"):
                return f"Done — {result.evidence['message']}"
            return "Done — the mission completed and was physically verified."
        if result.status == "failed":
            message = (result.error or {}).get("message") or "Verification failed."
            return f"The mission failed during execution: {message}"
        if result.status == "partial":
            return "The mission is partially complete; final state was not fully verified."
        if result.status == "permission_required":
            return "The operating system requires elevation for this action."
        if result.status == "ambiguous":
            return result.evidence.get("clarification_question", "The target is ambiguous.")
        return f"Mission status: {result.status}."


_global_supervisor: Optional[MasterSupervisor] = None


def get_master_supervisor() -> MasterSupervisor:
    global _global_supervisor
    if _global_supervisor is None:
        _global_supervisor = MasterSupervisor()
    return _global_supervisor
