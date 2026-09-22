"""Kratos Bridge connecting Gemini Live multimodal layer to existing Kratos runtime."""
from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from typing import Any, Dict, Optional

from .events import LiveState, LiveStatusHub

logger = logging.getLogger(__name__)


class KratosBridge:
    """Bridge between Gemini Live perception and Kratos autonomous execution brain."""

    def __init__(
        self,
        runtime: Optional[Any] = None,
        status_hub: Optional[LiveStatusHub] = None,
    ) -> None:
        if runtime is None:
            from kratos_agent.main import runtime as default_runtime
            self.runtime = default_runtime
        else:
            self.runtime = runtime

        self.status_hub = status_hub
        self.active_task_id: Optional[str] = None
        self.active_task_desc: Optional[str] = None
        self._lock = threading.Lock()
        self._active_future: Optional[asyncio.Future[Any]] = None

    def is_busy(self) -> bool:
        with self._lock:
            return self.active_task_id is not None

    async def submit_task(
        self,
        task_description: str,
        visual_context: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Submits an autonomous engineering task to Kratos runtime with echo & duplicate protection (§27, §30)."""
        from kratos_agent.live.echo_guard import get_echo_guard
        from kratos_agent.core.task_deduplicator import get_task_deduplicator

        if get_echo_guard().should_suppress_mic():
            logger.info(f"[LiveBridge] Suppressed echo task: {task_description}")
            return {"status": "echo_suppressed", "message": "Ignored microphone input during or right after TTS playback."}

        if get_task_deduplicator().is_duplicate(task_description):
            logger.info(f"[LiveBridge] Suppressed duplicate task: {task_description}")
            return {"status": "duplicate_suppressed", "message": "Duplicate task received within 3s window."}

        with self._lock:
            if self.active_task_id is not None and not force:
                logger.info("[GEMINI] Task rejected — Kratos is busy")
                return {
                    "status": "busy",
                    "message": f"I'm already working on a task: '{self.active_task_desc}'. Would you like me to cancel it first?",
                    "summary": f"Kratos is busy with: {self.active_task_desc}",
                    "active_task_id": self.active_task_id,
                }

            task_id = str(uuid.uuid4())[:8]
            self.active_task_id = task_id
            self.active_task_desc = task_description

        if self.status_hub:
            self.status_hub.update(active_task_id=task_id, current_state=LiveState.EXECUTING)

        # Assemble task with visual context if present
        full_query = task_description.strip()
        if visual_context and visual_context.strip():
            full_query = (
                f"{full_query}\n\n"
                f"[Visual Context from screen/camera]:\n{visual_context.strip()}"
            )
        logger.info(f"[GEMINI] Intent: AGENT_TASK")
        logger.info(f"[GEMINI] Task handoff → Kratos Brain: {task_description[:80]}")
        logger.info(f"[KRATOS] Task received [{task_id}]: {task_description[:80]}")
        print(f"\n⚡ [Voice Task Received]: {task_description}\n", flush=True)

        def _execute_in_background() -> None:
            try:
                logger.info(f"[KRATOS] Execution started [{task_id}]")
                if hasattr(self.runtime, "clear_cancel"):
                    self.runtime.clear_cancel()
                # Run agent completely autonomously
                self.runtime.run_agent(full_query, agent_mode=True)
                logger.info(f"[KRATOS] Task completed [{task_id}]")
            except Exception as e:
                logger.error(f"[KRATOS] Execution error in task {task_id}: {e}")
            finally:
                with self._lock:
                    if self.active_task_id == task_id:
                        self.active_task_id = None
                        self.active_task_desc = None
                if self.status_hub:
                    self.status_hub.update(active_task_id=None, current_state=LiveState.IDLE)

        # Start execution in a background thread so Gemini is not blocked
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _execute_in_background)

        # Return instantly to Gemini
        return {
            "status": "started",
            "task_id": task_id,
            "summary": "Task started. I will monitor the screen.",
        }

    def cancel_active_task(self) -> Dict[str, Any]:
        """Cancels the currently running Kratos task."""
        with self._lock:
            task_id = self.active_task_id
            self.active_task_id = None
            self.active_task_desc = None

        if hasattr(self.runtime, "cancel"):
            self.runtime.cancel()

        if self.status_hub:
            self.status_hub.update(active_task_id=None, current_state=LiveState.IDLE)


        if task_id:
            logger.info(f"[KratosBridge] Cancelled active task {task_id}")
            return {"status": "cancelled", "message": f"Task {task_id} has been cancelled."}
        return {"status": "idle", "message": "No active task was running."}

    def get_status(self) -> Dict[str, Any]:
        """Returns the current Kratos execution status."""
        plan_dict = None
        if hasattr(self.runtime, "loop") and getattr(self.runtime.loop, "current_plan", None):
            plan_dict = self.runtime.loop.current_plan.to_dict()

        return {
            "is_busy": self.is_busy(),
            "active_task_id": self.active_task_id,
            "active_task_desc": self.active_task_desc,
            "plan": plan_dict,
        }
