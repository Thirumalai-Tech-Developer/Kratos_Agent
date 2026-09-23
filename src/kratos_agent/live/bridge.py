"""Kratos Bridge connecting Gemini Live Master to OmniRoute Slave execution bus."""
from __future__ import annotations

import asyncio
import logging
import re
import threading
import uuid
from typing import Any, Dict, Optional

from kratos_agent.master.protocol import MasterCommand, SlaveAck, SlaveResult, get_command_bus
from kratos_agent.master.supervisor import MasterSupervisor, get_master_supervisor
from kratos_agent.slave.executor import SlaveExecutor, get_slave_executor
from .events import LiveState, LiveStatusHub

logger = logging.getLogger(__name__)


class KratosBridge:
    """Upgraded bridge orchestrating MasterCommandQueue, SlaveResultQueue, and status."""

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
        self.supervisor = get_master_supervisor()
        self.slave_executor = get_slave_executor()
        self.slave_executor.runtime = self.runtime

        # Ensure slave executor is running
        try:
            loop = asyncio.get_running_loop()
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
    ) -> Dict[str, Any]:
        """Submits an actionable command from Master to Slave via CommandBus."""
        from kratos_agent.live.echo_guard import get_echo_guard
        from kratos_agent.core.task_deduplicator import get_task_deduplicator

        if get_echo_guard().should_suppress_mic():
            logger.info(f"[LiveBridge] Suppressed echo task: {task_description}")
            return {"status": "echo_suppressed", "message": "Ignored microphone input during or right after TTS playback."}

        if get_task_deduplicator().is_duplicate(task_description):
            logger.info(f"[LiveBridge] Suppressed duplicate task: {task_description}")
            return {"status": "duplicate_suppressed", "message": "Duplicate task received within 3s window."}

        # Auto-detect intent if not explicitly set
        desc_lower = task_description.lower().strip()
        params = dict(parameters or {})
        constrs = dict(constraints or {})
        exp_res = dict(expected_result or {})

        if action == "generic_task":
            from kratos_agent.computer.browser.intent import is_pure_browser_media_request, is_pure_app_launch_request
            if is_pure_browser_media_request(task_description):
                action = "browser.youtube.play"
                params["query"] = task_description.replace("open youtube and play", "").replace("play", "").replace("on youtube", "").strip()
                constrs.update({"reuse_existing_chrome_window": True, "create_one_task_tab": True, "reuse_task_tab": True, "foreground_required": True})
                exp_res.update({"video_playing": True, "playback_advancing": True})
            elif is_pure_app_launch_request(task_description):
                action = "open_application"
                app_text = re.sub(r"^(?:can you|could you|please)\s+", "", task_description.strip(), flags=re.IGNORECASE)
                params["app_name"] = re.sub(r"^(?:open|launch|start)\s+", "", app_text, flags=re.IGNORECASE).strip()
            elif any(desc_lower.startswith(p) for p in ("search ", "find ", "who is ", "what is ")):
                action = "search"
                params["query"] = task_description

        # Start slave background loop if not already started
        self.slave_executor.start()

        if self.status_hub:
            self.status_hub.update(current_state=LiveState.EXECUTING)

        logger.info(f"[MASTER -> SLAVE] Delegating action='{action}', objective='{task_description[:80]}'")
        print(f"\n⚡ [Master -> Slave Command]: {task_description} ({action})\n", flush=True)

        res = await self.supervisor.submit_delegated_task(
            objective=task_description,
            action=action,
            parameters=params,
            constraints=constrs,
            expected_result=exp_res,
            priority=priority,
            timeout=timeout,
            context={"visual_context": visual_context} if visual_context else None,
            force=force,
        )

        if self.status_hub and res.get("task_id"):
            self.status_hub.update(active_task_id=res["task_id"])

        return res

    async def cancel_active_task(self) -> Dict[str, Any]:
        """Cancels active task across the Master/Slave bus."""
        res = await self.supervisor.cancel_active_task()
        if hasattr(self.runtime, "cancel"):
            self.runtime.cancel()
        if self.status_hub:
            self.status_hub.update(active_task_id=None, current_state=LiveState.IDLE)
        return res

    def get_status(self) -> Dict[str, Any]:
        """Returns the current Master/Slave execution status."""
        plan_dict = None
        if hasattr(self.runtime, "loop") and getattr(self.runtime.loop, "current_plan", None):
            plan_dict = self.runtime.loop.current_plan.to_dict()

        return {
            "is_busy": self.is_busy(),
            "active_task_id": self.supervisor.active_task_id,
            "active_task_desc": self.supervisor.active_objective,
            "plan": plan_dict,
        }
