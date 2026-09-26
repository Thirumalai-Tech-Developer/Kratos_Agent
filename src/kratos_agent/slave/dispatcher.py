from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from kratos_agent.master.protocol import MasterCommand, SlaveResult


class SlaveDispatcher:
    """Capability-to-executor dispatcher. It never parses user language."""

    def __init__(self, owner: Any) -> None:
        self.owner = owner
        self._handlers: dict[str, Callable[[MasterCommand], Awaitable[SlaveResult]]] = {
            "browser.youtube.play": owner._execute_youtube_play,
            "browser.youtube.pause": owner._execute_browser_pause,
            "browser.youtube.resume": owner._execute_browser_resume,
            "browser.navigate": owner._execute_browser_open,
            "browser.open": owner._execute_browser_open,
            "app.launch": owner._execute_app_launch,
            "open_application": owner._execute_app_launch,
            "search": owner._execute_search,
            "search.web": owner._execute_search,
            "observe": owner._execute_observe,
            "screen.capture": owner._execute_observe,
            "vision.inspect": owner._execute_observe,
        }

    async def dispatch(self, cmd: MasterCommand) -> SlaveResult:
        action = cmd.action.lower()

        if action == "whatsapp.send_message":
            from kratos_agent.executors.whatsapp import WhatsAppExecutor
            contact = str(cmd.parameters.get("contact") or "").strip()
            message = str(cmd.parameters.get("message") or "")
            if not contact or not message:
                return SlaveResult(
                    command_id=cmd.command_id,
                    task_id=cmd.task_id,
                    status="failed",
                    verified=False,
                    terminal=True,
                    error={
                        "type": "TOOL_VALIDATION_ERROR",
                        "message": "whatsapp.send_message requires structured contact and message parameters.",
                    },
                )
            result = await WhatsAppExecutor().execute(contact, message)
            verified = bool(result.get("verified"))
            return SlaveResult(
                command_id=cmd.command_id,
                task_id=cmd.task_id,
                status="success" if result.get("ok") and verified else "failed",
                verified=verified,
                terminal=True,
                state="MESSAGE_SENT" if verified else "MESSAGE_NOT_VERIFIED",
                evidence=result,
                error=None if verified else {
                    "type": "WHATSAPP_SEND_FAILED",
                    "message": result.get("error") or result.get("detail") or "WhatsApp message was not verified.",
                },
            )

        handler = self._handlers.get(action)
        if handler is not None:
            return await handler(cmd)

        # Unknown capabilities are not reinterpreted as English. They are handed to
        # the existing structured agent runtime as the explicit mission fallback.
        return await self.owner._execute_agent_task(cmd)
