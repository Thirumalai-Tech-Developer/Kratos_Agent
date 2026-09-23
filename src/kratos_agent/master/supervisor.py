"""Master supervisor coordinating Gemini Live Master and the CommandBus."""
from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from .protocol import (
    CommandAction,
    CommandPriority,
    MasterCommand,
    SlaveAck,
    SlaveResult,
    get_command_bus,
)

logger = logging.getLogger(__name__)


class MasterSupervisor:
    """Supervises task execution delegated from Gemini Live Master to OmniRoute Slave."""

    def __init__(self, session_id: Optional[str] = None) -> None:
        self.session_id = session_id or f"LIVE-{uuid.uuid4().hex[:6].upper()}"
        self.command_bus = get_command_bus()
        self.active_task_id: Optional[str] = None
        self.active_command_id: Optional[str] = None
        self.active_objective: Optional[str] = None
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
    ) -> Dict[str, Any]:
        """Submits a structured MasterCommand to the Slave via the CommandBus."""
        with self._lock:
            if self.active_task_id is not None and not force and priority.lower() != "cancel":
                logger.info(f"[MasterSupervisor] Rejecting command — busy with {self.active_task_id}")
                return {
                    "status": "busy",
                    "accepted": False,
                    "message": f"I am already working on: '{self.active_objective}'. Would you like to cancel it?",
                    "active_task_id": self.active_task_id,
                }

        cmd = MasterCommand.create(
            objective=objective,
            action=action,
            parameters=parameters or {},
            constraints=constraints or {},
            expected_result=expected_result or {},
            context=context or {},
            priority=priority,
            timeout=timeout,
            session_id=self.session_id,
        )

        with self._lock:
            self.active_task_id = cmd.task_id
            self.active_command_id = cmd.command_id
            self.active_objective = objective

        logger.info(f"[MasterSupervisor] Submitting command {cmd.command_id} ({cmd.action}) for task {cmd.task_id}")
        ack_fut, result_fut = await self.command_bus.send_command(cmd)

        # Wait for immediate Slave acknowledgement with short timeout (e.g. 5s)
        try:
            ack: SlaveAck = await asyncio.wait_for(ack_fut, timeout=5.0)
            if not ack.accepted:
                with self._lock:
                    if self.active_command_id == cmd.command_id:
                        self.active_task_id = None
                        self.active_command_id = None
                        self.active_objective = None
                return {
                    "status": "rejected",
                    "accepted": False,
                    "command_id": cmd.command_id,
                    "task_id": cmd.task_id,
                    "message": ack.message or "Slave rejected the command.",
                }
        except asyncio.TimeoutError:
            logger.warning(f"[MasterSupervisor] Timeout waiting for Slave ACK for {cmd.command_id}")
            # Proceed optimistically if ack delayed
            ack = SlaveAck(command_id=cmd.command_id, task_id=cmd.task_id, accepted=True, status="accepted")

        # Background task to await result and notify speech callback
        asyncio.create_task(self._await_result(cmd, result_fut))

        return {
            "status": "started",
            "accepted": True,
            "command_id": cmd.command_id,
            "task_id": cmd.task_id,
            "summary": f"Task '{objective}' delegated to Slave. Waiting for verified execution.",
        }

    async def _await_result(self, cmd: MasterCommand, result_fut: asyncio.Future[SlaveResult]) -> None:
        try:
            result = await asyncio.wait_for(result_fut, timeout=cmd.timeout)
            logger.info(f"[MasterSupervisor] Received SlaveResult for {result.command_id}: status={result.status}, verified={result.verified}")
            spoken_summary = self.format_response_for_master(result)
            if self._on_speech_feedback and spoken_summary:
                self._on_speech_feedback(spoken_summary)
        except asyncio.TimeoutError:
            logger.error(f"[MasterSupervisor] Execution timeout ({cmd.timeout}s) for {cmd.command_id}")
            if self._on_speech_feedback:
                self._on_speech_feedback("The execution timed out before verifying the result.")
        except Exception as e:
            logger.error(f"[MasterSupervisor] Error awaiting result for {cmd.command_id}: {e}")
        finally:
            with self._lock:
                if self.active_command_id == cmd.command_id:
                    self.active_task_id = None
                    self.active_command_id = None
                    self.active_objective = None

    async def cancel_active_task(self, reason: str = "User cancelled") -> Dict[str, Any]:
        """Cancels the currently running task."""
        with self._lock:
            tid = self.active_task_id
            self.active_task_id = None
            self.active_command_id = None
            self.active_objective = None

        if tid:
            await self.command_bus.cancel_task(tid, reason)
            return {"status": "cancelled", "task_id": tid, "message": f"Task {tid} cancellation sent to Slave."}
        return {"status": "idle", "message": "No active task to cancel."}

    def format_response_for_master(self, result: SlaveResult) -> str:
        """Transforms a structured SlaveResult into concise spoken text for the Master to speak."""
        if result.is_success():
            if result.state == "VIDEO_PLAYING":
                return "Done — the video is playing."
            elif result.state == "SEARCH_RESULTS":
                return "Done — search results are displayed on screen."
            elif result.state == "APPLICATION_OPENED":
                return "Done — the application is open and ready in the foreground."
            elif result.evidence.get("message"):
                return f"Done — {result.evidence['message']}"
            return "Done — the task completed successfully and verified."

        elif result.status == "failed":
            err_msg = ""
            if result.error:
                err_msg = result.error.get("message") or str(result.error)
            elif result.evidence.get("error"):
                err_msg = str(result.evidence["error"])
            return f"I encountered an issue executing the task: {err_msg or 'Verification failed.'}"

        elif result.status == "partial":
            done_items = result.evidence.get("completed_steps", [])
            return f"Partially completed: {', '.join(done_items) if done_items else 'initial steps done'}."

        elif result.status == "permission_required":
            target = result.evidence.get("target", "operation")
            return f"Permission required to perform {target}. Would you like me to proceed?"

        elif result.status == "ambiguous":
            return result.evidence.get("clarification_question", "Could you please clarify your request?")

        return "Task status received."


# Global supervisor singleton
_global_supervisor: Optional[MasterSupervisor] = None


def get_master_supervisor() -> MasterSupervisor:
    global _global_supervisor
    if _global_supervisor is None:
        _global_supervisor = MasterSupervisor()
    return _global_supervisor
