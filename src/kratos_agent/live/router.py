"""Intent routing and native Live function declarations for Kratos."""
from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from google.genai import types

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
    workspace: Optional[str] = None
    vision_required: bool = False
    confirmation_required: bool = False
    priority: str = "normal"
    clarification_question: Optional[str] = None


class LiveRouter:
    """Manages Gemini Live tool declarations, 6-priority decision matrix, and intent dispatching."""

    def __init__(
        self,
        bridge: KratosBridge,
        capture_screen_handler: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.bridge = bridge
        self.capture_screen_handler = capture_screen_handler

    def get_tool_declarations(self) -> List[types.Tool]:
        """Returns the small, dedicated Master-level tool declarations for Gemini Live Master."""
        delegate_task_fn = types.FunctionDeclaration(
            name="delegate_task",
            behavior="NON_BLOCKING",
            description=(
                "Delegate an autonomous execution command to the Slave agent (OmniRoute / Brain runtime). "
                "Call this whenever the user wants to open/close/launch any application, browse/click/type/search "
                "on websites, play videos/media, run terminal commands, write/edit code, or execute any computer action. "
                "Do NOT execute desktop actions yourself. Provide explicit objective, action, parameters, constraints, "
                "and expected results to the Slave."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "objective": types.Schema(
                        type="STRING",
                        description="High-level goal of what the Slave should achieve.",
                    ),
                    "action": types.Schema(
                        type="STRING",
                        description="Target action (e.g. 'browser.youtube.play', 'open_application', 'browser.navigate', 'generic_task').",
                    ),
                    "parameters": types.Schema(
                        type="OBJECT",
                        description="Key-value arguments for the action (e.g. query, app_name, url).",
                    ),
                    "constraints": types.Schema(
                        type="OBJECT",
                        description="Execution constraints (e.g. reuse_existing_chrome_window, create_one_task_tab).",
                    ),
                    "expected_result": types.Schema(
                        type="OBJECT",
                        description="Expected physical evidence (e.g. video_playing, playback_advancing).",
                    ),
                    "priority": types.Schema(
                        type="STRING",
                        description="Priority: 'low', 'normal', 'high', 'urgent'.",
                    ),
                },
                required=["objective"],
            ),
        )

        search_fn = types.FunctionDeclaration(
            name="search",
            behavior="NON_BLOCKING",
            description=(
                "Search the web, technical documentation, or GitHub via Kratos Search Fabric. "
                "Use this to answer factual questions, find downloads, or look up information."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "query": types.Schema(type="STRING", description="Search query string."),
                    "mode": types.Schema(type="STRING", description="Search mode: 'fast', 'standard', 'deep', 'research'."),
                },
                required=["query"],
            ),
        )

        observe_fn = types.FunctionDeclaration(
            name="observe",
            behavior="NON_BLOCKING",
            description="Capture and inspect a fresh desktop screen frame or specific application window.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "reason": types.Schema(type="STRING", description="Reason for observation."),
                },
            ),
        )

        get_status_fn = types.FunctionDeclaration(
            name="get_task_status",
            behavior="NON_BLOCKING",
            description="Get the status, plan, and progress of the active Slave task.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "task_id": types.Schema(type="STRING", description="Optional specific task ID."),
                },
            ),
        )

        cancel_task_fn = types.FunctionDeclaration(
            name="cancel_task",
            behavior="NON_BLOCKING",
            description="Immediately stop and abort the active Slave execution task.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "reason": types.Schema(type="STRING", description="Reason for cancellation."),
                },
            ),
        )

        continue_task_fn = types.FunctionDeclaration(
            name="continue_task",
            behavior="NON_BLOCKING",
            description="Instruct the Slave to continue the active browser session or task tab without creating a new window.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "instructions": types.Schema(type="STRING", description="Continuation instructions."),
                },
                required=["instructions"],
            ),
        )

        ask_user_fn = types.FunctionDeclaration(
            name="ask_user",
            behavior="NON_BLOCKING",
            description="Ask the user for confirmation or clarification before proceeding with high-impact actions.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "question": types.Schema(type="STRING", description="Clarification question for the user."),
                },
                required=["question"],
            ),
        )

        # Legacy alias function for compatibility
        start_task_fn = types.FunctionDeclaration(
            name="start_agent_task",
            behavior="NON_BLOCKING",
            description="Legacy alias for delegate_task. Submits task to Slave.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "task_description": types.Schema(type="STRING", description="Task description."),
                    "visual_context": types.Schema(type="STRING", description="Visual context."),
                    "priority": types.Schema(type="STRING", description="Priority."),
                },
                required=["task_description"],
            ),
        )

        return [
            types.Tool(
                function_declarations=[
                    delegate_task_fn,
                    search_fn,
                    observe_fn,
                    get_status_fn,
                    cancel_task_fn,
                    continue_task_fn,
                    ask_user_fn,
                    start_task_fn,
                ]
            )
        ]

    async def handle_tool_call(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatches Master tool calls to Bridge, SearchFabric, or Perception."""
        logger.info(f"[LiveRouter] Received Master tool call: {name} with args: {args}")

        if name in ("delegate_task", "start_agent_task"):
            objective = str(args.get("objective") or args.get("task_description", "")).strip()
            if not objective:
                return {"status": "error", "message": "Missing task objective."}

            action = str(args.get("action", "generic_task"))
            params = args.get("parameters") or {}
            constrs = args.get("constraints") or {}
            exp_res = args.get("expected_result") or {}
            priority = str(args.get("priority", "normal"))
            vis_ctx = args.get("visual_context")

            return await self.bridge.submit_task(
                task_description=objective,
                visual_context=vis_ctx,
                action=action,
                parameters=params,
                constraints=constrs,
                expected_result=exp_res,
                priority=priority,
            )

        elif name == "search":
            query = str(args.get("query", "")).strip()
            mode = str(args.get("mode", "standard"))
            if not query:
                return {"status": "error", "message": "Missing search query."}

            from kratos_agent.search import get_search_router
            router = get_search_router()
            resp = await router.search(query, mode=mode)
            return {
                "status": "success",
                "total_results": resp.total_results,
                "answer": resp.answer,
                "results": [r.to_dict() for r in resp.results[:5]],
                "citations": resp.citations,
            }

        elif name in ("observe", "capture_screen_context"):
            reason = str(args.get("reason", "Visual inspection requested")).strip()
            logger.info(f"[LiveRouter] Observing screen on-demand. Reason: {reason}")
            if self.capture_screen_handler:
                try:
                    if inspect.iscoroutinefunction(self.capture_screen_handler):
                        res = await self.capture_screen_handler()
                    else:
                        res = self.capture_screen_handler()
                    if res is None or res is False:
                        return {"status": "error", "message": "Screen capture failed: no frame was captured."}
                    if isinstance(res, dict) and res.get("status") == "error":
                        err_msg = res.get("message") or res.get("error") or "Screen capture failed"
                        return {"status": "error", "message": f"Screen capture failed: {err_msg}"}
                    metadata = {}
                    if hasattr(res, "width") and hasattr(res, "height"):
                        metadata = {"width": res.width, "height": res.height}
                    return {
                        "status": "success",
                        "message": "Desktop screen captured and streamed to your visual perception.",
                        **metadata,
                    }
                except Exception as e:
                    return {"status": "error", "message": f"Screen capture exception: {e}"}
            return {"status": "error", "message": "Screen capture handler not configured."}

        elif name in ("cancel_task", "cancel_active_task"):
            return await self.bridge.cancel_active_task()

        elif name == "get_task_status":
            return self.bridge.get_status()

        elif name == "continue_task":
            instructions = str(args.get("instructions", "")).strip()
            return await self.bridge.submit_task(
                task_description=instructions,
                action="continue",
                parameters={"instructions": instructions},
            )

        elif name == "ask_user":
            q = str(args.get("question", "")).strip()
            return {"status": "waiting_user_response", "question": q}

        else:
            return {"status": "error", "message": f"Unknown Master tool: {name}"}


    def evaluate_request(
        self,
        user_text: str,
        active_task: Optional[str] = None,
        workspace: Optional[str] = None,
        recent_context: Optional[str] = None,
        has_visual_context: bool = False,
    ) -> StructuredTask:
        """
        Evaluates a user request according to the strict 6-Priority Decision Matrix:
        1. Context Resolution
        2. Explicit User Intent
        3. Safety / Approval Check
        4. Vision Requirement
        5. Actionability
        6. Final Routing
        """
        import re

        raw = user_text.strip()
        cleaned = re.sub(r"[^\w\s]", "", raw.lower()).strip()

        # Load session history command
        if cleaned.startswith("load") and "/load" in raw:
            return StructuredTask(
                intent=IntentKind.AGENT_TASK,
                task="Load previous session history.",
                workspace=workspace,
            )

        # Cancellation check
        if any(cleaned.startswith(p) for p in ("stop", "cancel", "abort", "halt")) or cleaned in ("never mind", "stop it", "shut up"):
            return StructuredTask(
                intent=IntentKind.CANCEL,
                task="Cancel the active task",
                workspace=workspace,
            )

        # Status check
        if any(p in cleaned for p in ("what are you doing", "task status", "progress update", "how is it going", "what's your status")):
            return StructuredTask(
                intent=IntentKind.STATUS,
                task="Report current task status",
                workspace=workspace,
            )

        # Priority 1: Context Resolution
        resolved_text = raw
        if recent_context and any(cleaned == p or cleaned.startswith(p + " ") for p in ("fix that", "do that", "change that", "inspect that", "run that", "make it faster", "fix it")):
            resolved_text = f"{raw} (Context: {recent_context})"

        # Priority 2: Explicit User Intent
        explicit_chat = any(
            cleaned.startswith(p) or f" {p}" in cleaned
            for p in (
                "just explain", "dont change anything", "don't change anything",
                "only explain", "just tell me", "what is ", "what are ",
                "how does ", "how do ", "why is ", "why does ", "what do you think about"
            )
        )
        explicit_action = any(
            cleaned.startswith(p) or f" {p}" in cleaned
            for p in (
                "do it", "fix it", "create it", "run it", "build it", "make it",
                "fix this", "create a ", "build a ", "run the ", "modify the ",
                "install ", "delete ", "remove ", "deploy ", "start the "
            )
        )

        # Priority 3: Safety / Approval Check (potentially destructive or high impact)
        is_destructive = any(
            w in cleaned for w in (
                "delete all", "remove all", "drop database", "format drive",
                "rm -rf", "delete repository", "delete database", "permanently remove",
                "deploy to production", "publish release"
            )
        )
        if is_destructive:
            return StructuredTask(
                intent=IntentKind.CONFIRM,
                task=resolved_text,
                workspace=workspace,
                confirmation_required=True,
                priority="high",
                clarification_question="This is a potentially destructive action. Are you sure you want to proceed?",
            )

        # Priority 4: Vision Requirement
        vision_required = any(
            p in cleaned for p in (
                "look at this", "look at my screen", "on my screen", "what do you see",
                "what is this error", "explain what i am seeing", "explain what im seeing",
                "fix this error", "see this", "look here"
            )
        )

        # If reference is ambiguous without context
        if cleaned in ("fix it", "fix that", "delete that", "do that", "make it faster") and not recent_context and not active_task:
            return StructuredTask(
                intent=IntentKind.CLARIFY,
                task=resolved_text,
                workspace=workspace,
                clarification_question="Which file or component would you like me to work on?",
            )

        # Priority 5: Actionability Check (Explicit chat strictly overrides inferred action)
        action_verbs = (
            "fix", "build", "run", "test", "inspect", "create", "edit",
            "debug", "install", "deploy", "modify", "write", "open", "update", "restart",
            "close", "play", "download", "navigate", "browse", "click", "type",
            "search", "automate", "launch", "go", "start", "stop", "delete",
            "remove", "execute", "clone", "fetch", "push", "pull", "commit",
            "scaffold", "setup", "configure", "stream", "record", "screenshot",
        )
        # Tamil/Hindi/mixed-language action indicators
        multilingual_action_words = (
            "\u0b93\u0baa\u0ba9\u0bcd",    # ஓபன் (open)
            "\u0bb0\u0ba9\u0bcd",        # ரன் (run)
            "\u0baa\u0ba3\u0bcd\u0ba3\u0bc1",    # பண்ணு (do)
            "\u0baa\u0bcb",          # ப\u0bcb (go)
            "\u0ba4\u0bc7\u0b9f\u0bc1",      # த\u0bc7\u0b9f\u0bc1 (search)
            "\u0b89\u0bb0\u0bc1\u0bb5\u0bbe\u0b95\u0bcd\u0b95\u0bc1",  # உ\u0bb0\u0bc1\u0bb5\u0bbe\u0b95\u0bcd\u0b95\u0bc1 (create)
            "\u0b9a\u0bc6\u0baf\u0bcd",      # ச\u0bc6\u0baf\u0bcd (do/make)
            "\u0b85\u0b9f\u0bbf",        # அ\u0b9f\u0bbf (close/hit/type)
            "\u0b95\u0bbe\u0b9f\u0bcd\u0b9f\u0bc1",    # காட்டு (show)
            "\u0b9f\u0bc8\u0baa\u0bcd",      # டைப் (type)
            "\u0b8e\u0bb4\u0bc1\u0ba4\u0bc1",    # எழுது (write)
            "\u0baa\u0bbe\u0bb0\u0bcd",      # பார் (see/check)
            "\u0b9a\u0bb0\u0bbf",        # சரி (fix/correct)
            "\u0916\u094b\u0932\u094b",      # \u0916\u094b\u0932\u094b (open - Hindi)
            "\u091a\u0932\u093e\u0913",    # \u091a\u0932\u093e\u0913 (run - Hindi)
            "\u0915\u0930\u094b",        # \u0915\u0930\u094b (do - Hindi)
            "\u092c\u0928\u093e\u0913",    # \u092c\u0928\u093e\u0913 (create - Hindi)
            "\u0926\u093f\u0916\u093e\u0913",    # दिखाओ (show - Hindi)
            "\u0932\u093f\u0916\u094b",      # लिखो (write - Hindi)
        )
        words = set(cleaned.split())
        has_multilingual_action = any(w in raw for w in multilingual_action_words)
        is_actionable = (not explicit_chat) and (explicit_action or any(w in words for w in action_verbs) or has_multilingual_action)

        # Priority 6: Final Routing
        if vision_required and is_actionable:
            return StructuredTask(
                intent=IntentKind.VISION_AGENT_TASK,
                task=resolved_text,
                workspace=workspace,
                vision_required=True,
                confirmation_required=False,
            )
        elif vision_required and not is_actionable:
            return StructuredTask(
                intent=IntentKind.VISION_CHAT,
                task=resolved_text,
                workspace=workspace,
                vision_required=True,
                confirmation_required=False,
            )
        elif is_actionable:
            return StructuredTask(
                intent=IntentKind.AGENT_TASK,
                task=resolved_text,
                workspace=workspace,
                vision_required=False,
                confirmation_required=False,
            )
        else:
            return StructuredTask(
                intent=IntentKind.CHAT,
                task=resolved_text,
                workspace=workspace,
                vision_required=False,
                confirmation_required=False,
            )

    def classify_intent_fallback(self, text: str) -> IntentKind:
        """Heuristic intent classification for text fallback."""
        task = self.evaluate_request(text)
        return task.intent
