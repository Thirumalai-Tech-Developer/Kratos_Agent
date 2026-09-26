"""Gemini Live Perception & Intent Bridge for Kratos Beast.

Translates between Gemini Live multimodal perception (voice, screen, camera)
and Kratos Beast execution fabric. Gemini Live acts as EYES, EARS, and VOICE;
Kratos acts as BRAIN, HANDS, MEMORY, and VERIFICATION.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from kratos_agent.providers.base import ProviderError
from kratos_agent.providers.events import (
    AgentEvent,
    CanonicalEventType,
    redact_secrets,
)
from kratos_agent.providers.health import HealthStatus, ProviderHealth
from kratos_agent.providers.router import ProviderRouter

logger = logging.getLogger(__name__)


class VisualSource(str, Enum):
    SCREEN = "screen"
    CAMERA = "camera"
    WINDOW = "window"
    ERROR_MODAL = "error_modal"


@dataclass
class VisualContextSnapshot:
    """Sanitized, sampled visual context attached to a task."""
    source: VisualSource
    timestamp: float = field(default_factory=time.time)
    summary: str = ""
    image_ref: str | None = None
    width: int | None = None
    height: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.value,
            "timestamp": self.timestamp,
            "summary": redact_secrets(self.summary),
            "image_ref": self.image_ref,
            "width": self.width,
            "height": self.height,
        }


class GeminiLiveBridge:
    """Multimodal bridge connecting Gemini Live to Kratos Beast orchestration."""

    def __init__(
        self,
        router: ProviderRouter | None = None,
        screen_capture_fn: Callable[[], Any] | None = None,
        camera_capture_fn: Callable[[], Any] | None = None,
        speech_output_fn: Callable[[str], Any] | None = None,
    ) -> None:
        self.router = router or ProviderRouter()
        self.screen_capture_fn = screen_capture_fn
        self.camera_capture_fn = camera_capture_fn
        self.speech_output_fn = speech_output_fn

        # Failure isolation state: subsystem drops never bring down Kratos
        self._mic_healthy: bool = True
        self._speaker_healthy: bool = True
        self._camera_healthy: bool = True
        self._screen_healthy: bool = True
        self._live_connected: bool = False

        self._active_tasks: dict[str, dict[str, Any]] = {}
        self._last_screen_sample_time: float = 0.0
        self._screen_sample_interval: float = 2.0  # throttle screen captures

    def set_speech_output_callback(self, fn: Callable[[str], Any]) -> None:
        """Attach text-to-speech callback for spoken voice narration."""
        self.speech_output_fn = fn

    def probe_health(self) -> ProviderHealth:
        """Report component health with strict fault isolation."""
        details = (
            f"Live Connected: {self._live_connected}, "
            f"Mic: {'READY' if self._mic_healthy else 'OFFLINE'}, "
            f"Speaker: {'READY' if self._speaker_healthy else 'OFFLINE'}, "
            f"Screen: {'READY' if self._screen_healthy else 'OFFLINE'}, "
            f"Camera: {'READY' if self._camera_healthy else 'OFFLINE'}"
        )
        status = HealthStatus.READY if self._live_connected else HealthStatus.DEGRADED
        return ProviderHealth(
            provider="gemini_live",
            status=status,
            details=details,
        )

    async def capture_visual_context(
        self,
        source: VisualSource = VisualSource.SCREEN,
        force: bool = False,
    ) -> VisualContextSnapshot | None:
        """Sample visual context with rate limiting and fault isolation."""
        now = time.time()
        if not force and source == VisualSource.SCREEN and (now - self._last_screen_sample_time) < self._screen_sample_interval:
            logger.debug("Throttling screen capture for task delegation.")
            return None

        try:
            if source == VisualSource.SCREEN and self.screen_capture_fn:
                frame = self.screen_capture_fn()
                if asyncio.iscoroutine(frame):
                    frame = await frame
                self._last_screen_sample_time = now
                self._screen_healthy = True
                return VisualContextSnapshot(
                    source=VisualSource.SCREEN,
                    summary="Screen frame captured from active workspace.",
                    width=getattr(frame, "width", None),
                    height=getattr(frame, "height", None),
                )
            elif source == VisualSource.CAMERA and self.camera_capture_fn:
                frame = self.camera_capture_fn()
                if asyncio.iscoroutine(frame):
                    frame = await frame
                self._camera_healthy = True
                return VisualContextSnapshot(
                    source=VisualSource.CAMERA,
                    summary="Camera frame captured from active user view.",
                )
        except Exception as e:
            logger.warning("Visual context capture failed for %s: %s (gracefully isolated)", source.value, e)
            if source == VisualSource.SCREEN:
                self._screen_healthy = False
            else:
                self._camera_healthy = False
            return None

        return None

    async def delegate_task(
        self,
        task_description: str,
        session_id: str,
        visual_source: str | None = None,
        requested_provider: str | None = None,
    ) -> dict[str, Any]:
        """Entry point for Gemini Live to delegate a high-level task to Kratos."""
        import uuid
        task_id = f"live-{uuid.uuid4().hex[:8]}"

        # Sample visual context if requested
        visual_context: VisualContextSnapshot | None = None
        if visual_source:
            try:
                src = VisualSource(visual_source.lower())
                visual_context = await self.capture_visual_context(src)
            except ValueError:
                visual_context = await self.capture_visual_context(VisualSource.SCREEN)

        # Natural language intent parsing for provider routing
        intent = self.router.parse_natural_language_orchestration(task_description)
        selected_provider = requested_provider or intent.get("primary_provider")

        task_record = {
            "task_id": task_id,
            "session_id": session_id,
            "description": task_description,
            "status": "running",
            "provider": selected_provider,
            "created_at": time.time(),
            "visual_context": visual_context.to_dict() if visual_context else None,
            "events": [],
        }
        self._active_tasks[task_id] = task_record

        # Narrate start of task safely
        await self.narrate(f"Started task: {task_description[:50]}", priority=50)

        # Launch execution through ProviderRouter
        try:
            run = await self.router.execute_task(
                task_id=task_id,
                session_id=session_id,
                prompt=task_description,
                requested_provider=selected_provider,
                context={"visual_context": visual_context.to_dict() if visual_context else None},
            )
            task_record["status"] = "completed"
            task_record["output"] = run.output
            await self.narrate("Task completed successfully.", priority=70)
            return {
                "status": "success",
                "task_id": task_id,
                "provider": run.provider,
                "output": run.output,
            }
        except Exception as e:
            logger.error("Delegated task %s failed: %s", task_id, e)
            task_record["status"] = "failed"
            task_record["error"] = str(e)
            await self.narrate("Task execution encountered an error.", priority=90)
            return {
                "status": "error",
                "task_id": task_id,
                "error": str(e),
            }

    async def steer_task(self, task_id: str, instruction: str) -> dict[str, Any]:
        """Route mid-task turn steering from voice to the active provider."""
        record = self._active_tasks.get(task_id)
        if not record or record["status"] != "running":
            return {"status": "error", "message": f"Task {task_id} is not currently running."}

        provider_name = record.get("provider") or "codex"
        try:
            backend = self.router.registry.get(provider_name)
            await backend.steer(task_id, instruction)
            await self.narrate("Steering active task.", priority=60)
            return {"status": "success", "message": f"Steering instruction sent to {provider_name}."}
        except Exception as e:
            return {"status": "error", "message": f"Steering failed: {e}"}

    async def cancel_task(self, task_id: str) -> dict[str, Any]:
        """Cancel an active task and propagate interrupt to the assigned provider."""
        record = self._active_tasks.get(task_id)
        if not record:
            return {"status": "error", "message": f"Task {task_id} not found."}

        provider_name = record.get("provider")
        if provider_name:
            try:
                backend = self.router.registry.get(provider_name)
                await backend.interrupt(task_id)
            except Exception as e:
                logger.warning("Error interrupting provider %s: %s", provider_name, e)

        record["status"] = "cancelled"
        await self.narrate("Task cancelled.", priority=90)
        return {"status": "success", "message": f"Task {task_id} cancelled."}

    def get_task_status(self, task_id: str) -> dict[str, Any]:
        """Inspect status of a delegated task."""
        record = self._active_tasks.get(task_id)
        if not record:
            return {"status": "not_found", "task_id": task_id}
        return {
            "task_id": task_id,
            "status": record["status"],
            "provider": record.get("provider"),
            "created_at": record.get("created_at"),
            "output_preview": record.get("output", "")[:200] if "output" in record else None,
            "error": record.get("error"),
        }

    async def narrate(self, text: str, priority: int = 50) -> None:
        """Send voice narration update with secret redaction and fault isolation."""
        if not self.speech_output_fn:
            return

        clean = redact_secrets(text)
        try:
            res = self.speech_output_fn(clean)
            if asyncio.iscoroutine(res):
                await res
            self._speaker_healthy = True
        except Exception as e:
            logger.warning("Speech output failed: %s (gracefully isolated)", e)
            self._speaker_healthy = False
