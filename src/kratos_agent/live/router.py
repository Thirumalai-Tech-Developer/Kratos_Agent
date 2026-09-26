"""Gemini Live tool surface for Kratos structured semantic execution."""
from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from google.genai import types

from kratos_agent.semantic.intent import mission_from_tool_call
from kratos_agent.semantic.schemas import MissionIntent

from .bridge import KratosBridge

logger = logging.getLogger(__name__)


class IntentKind(str, Enum):
    CHAT = "chat"
    VISION = "vision"
    VISION_CHAT = "vision"
    AGENT_TASK = "agent_task"
    VISION_AGENT_TASK = "vision_agent_task"
    CLARIFY = "clarify"
    CONFIRM = "confirm"
    STATUS = "status"
    CANCEL = "cancel"


@dataclass
class StructuredTask:
    intent: IntentKind
    task: str
    workspace: str | None = None
    vision_required: bool = False
    confirmation_required: bool = False
    priority: str = "normal"
    clarification_question: str | None = None


class LiveRouter:
    """Only dispatches structured Gemini decisions; it never classifies English."""

    def __init__(
        self,
        bridge: KratosBridge,
        capture_screen_handler: Callable[[], Any] | None = None,
        diagnostics_handler: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.bridge = bridge
        self.capture_screen_handler = capture_screen_handler
        self.diagnostics_handler = diagnostics_handler

    def set_diagnostics_handler(self, handler: Callable[[], dict[str, Any]] | None) -> None:
        """Attach Live runtime diagnostics to the structured status tool."""
        self.diagnostics_handler = handler

    def get_tool_declarations(self) -> list[types.Tool]:
        def obj_schema(properties: dict[str, types.Schema], required: list[str] | None = None) -> types.Schema:
            return types.Schema(type="OBJECT", properties=properties, required=required or [])

        execute_mission = types.FunctionDeclaration(
            name="execute_mission",
            behavior="NON_BLOCKING",
            description=(
                "Convert the user's natural-language request into one structured mission for Kratos Master. "
                "You own semantic intent. Supply the complete mission plus capability and structured arguments "
                "when you know them. The returned result is authoritative: wait for it before claiming success "
                "and use its error/evidence fields when execution fails. Never call this from a phrase parser; "
                "decide from meaning and multimodal context."
            ),
            parameters=obj_schema(
                {
                    "mission": types.Schema(type="STRING", description="The complete intended end-state mission in natural language."),
                    "capability": types.Schema(type="STRING", description="Optional canonical capability such as browser.youtube.play or whatsapp.send_message."),
                    "arguments": types.Schema(type="OBJECT", description="Structured capability arguments."),
                    "constraints": types.Schema(type="OBJECT", description="Execution constraints such as browser/session reuse."),
                    "expected_state": types.Schema(type="OBJECT", description="Physical evidence required for completion."),
                    "visual_context": types.Schema(type="STRING", description="Relevant fresh visual context when the mission depends on the screen."),
                    "priority": types.Schema(type="STRING", description="low, normal, high, urgent"),
                },
                ["mission"],
            ),
        )

        observe = types.FunctionDeclaration(
            name="observe",
            behavior="NON_BLOCKING",
            description="Capture a fresh screen observation when visual grounding is required.",
            parameters=obj_schema({
                "reason": types.Schema(type="STRING", description="Why a fresh observation is needed."),
            }),
        )

        search = types.FunctionDeclaration(
            name="search",
            behavior="NON_BLOCKING",
            description="Search the web, technical documentation, or GitHub through the existing Search Fabric.",
            parameters=obj_schema({
                "query": types.Schema(type="STRING", description="Search query."),
                "mode": types.Schema(type="STRING", description="fast, standard, deep, or research"),
            }, ["query"]),
        )

        status = types.FunctionDeclaration(
            name="get_task_status",
            behavior="NON_BLOCKING",
            description="Inspect current mission/task state, Live connection health, and the latest structured diagnostic. Use for error/status questions.",
            parameters=obj_schema({
                "task_id": types.Schema(type="STRING", description="Optional task id."),
            }),
        )

        cancel = types.FunctionDeclaration(
            name="cancel_task",
            behavior="NON_BLOCKING",
            description="Cancel the active mission.",
            parameters=obj_schema({
                "reason": types.Schema(type="STRING", description="Cancellation reason."),
            }),
        )

        cont = types.FunctionDeclaration(
            name="continue_task",
            behavior="NON_BLOCKING",
            description="Continue the active mission using its existing browser/application/task context.",
            parameters=obj_schema({
                "instructions": types.Schema(type="STRING", description="Continuation instructions."),
            }, ["instructions"]),
        )

        ask_user = types.FunctionDeclaration(
            name="ask_user",
            behavior="NON_BLOCKING",
            description="Ask the user only when semantic ambiguity prevents safe continuation.",
            parameters=obj_schema({
                "question": types.Schema(type="STRING", description="Clarifying question."),
            }, ["question"]),
        )

        return [types.Tool(function_declarations=[execute_mission, observe, search, status, cancel, cont, ask_user])]

    async def handle_tool_call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        logger.info("[LiveRouter] structured tool=%s args=%s", name, args)

        if name in {"execute_mission", "delegate_task", "start_agent_task"}:
            mission: MissionIntent = mission_from_tool_call(args)
            if not mission.goal:
                return {
                    "status": "error",
                    "error_type": "validation_error",
                    "message": "Gemini returned an empty mission.",
                }
            return await self.bridge.submit_task(
                task_description=mission.goal,
                action=mission.capability or "generic_task",
                parameters=mission.arguments,
                constraints=mission.constraints,
                expected_result=mission.expected_result,
                visual_context=mission.visual_context,
                priority=mission.priority,
                request_id=str(args.get("request_id") or ""),
                turn_id=str(args.get("turn_id") or ""),
                tool_call_id=str(args.get("tool_call_id") or ""),
                wait_for_result=(name == "execute_mission"),
            )

        if name == "search":
            query = str(args.get("query", "")).strip()
            if not query:
                return {"status": "error", "error_type": "validation_error", "message": "Search query is required."}
            from kratos_agent.search import get_search_router
            response = await get_search_router().search(query, mode=str(args.get("mode", "standard")))
            return {
                "status": "success",
                "total_results": response.total_results,
                "answer": response.answer,
                "results": [r.to_dict() for r in response.results[:5]],
                "citations": response.citations,
            }

        if name == "observe":
            reason = str(args.get("reason") or "fresh visual observation")
            if not self.capture_screen_handler:
                return {"status": "error", "error_type": "configuration_error", "message": "Screen capture handler is not configured."}
            try:
                result = self.capture_screen_handler()
                if inspect.isawaitable(result):
                    result = await result
                if result is None or result is False:
                    return {"status": "error", "error_type": "capture_error", "message": f"Screen observation failed: {reason}"}
                meta = {}
                if hasattr(result, "width"):
                    meta["width"] = result.width
                if hasattr(result, "height"):
                    meta["height"] = result.height
                return {"status": "success", "message": "Fresh screen observation captured.", **meta}
            except Exception as exc:
                logger.exception("screen observation failed")
                return {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "message": str(exc) or type(exc).__name__,
                }

        if name == "get_task_status":
            try:
                status = self.bridge.get_status(task_id=str(args.get("task_id") or "") or None)
                if self.diagnostics_handler is not None:
                    try:
                        status["live"] = dict(self.diagnostics_handler() or {})
                    except Exception as exc:
                        status["live"] = {
                            "healthy": False,
                            "error": {"type": type(exc).__name__, "message": str(exc) or type(exc).__name__},
                        }
                return status
            except Exception as exc:
                logger.exception("task status lookup failed")
                return {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "message": str(exc) or type(exc).__name__,
                    "stage": "status_lookup",
                }

        if name == "cancel_task":
            return await self.bridge.cancel_active_task()

        if name == "continue_task":
            instructions = str(args.get("instructions") or "").strip()
            if not instructions:
                return {"status": "error", "error_type": "validation_error", "message": "Continuation instructions are required."}
            return await self.bridge.submit_task(
                task_description=instructions,
                action="continue",
                parameters={"instructions": instructions},
            )

        if name == "ask_user":
            return {
                "status": "waiting_user_response",
                "question": str(args.get("question") or "What should I do next?"),
            }

        return {"status": "error", "error_type": "unknown_tool", "message": f"Unknown Gemini tool: {name}"}

    def evaluate_request(
        self,
        user_text: str,
        active_task: str | None = None,
        workspace: str | None = None,
        recent_context: str | None = None,
        has_visual_context: bool = False,
    ) -> StructuredTask:
        """Compatibility API only. It deliberately performs no semantic classification."""
        return StructuredTask(
            intent=IntentKind.AGENT_TASK,
            task=user_text.strip(),
            workspace=workspace,
            vision_required=has_visual_context,
        )

    def classify_intent_fallback(self, text: str) -> IntentKind:
        return IntentKind.AGENT_TASK
