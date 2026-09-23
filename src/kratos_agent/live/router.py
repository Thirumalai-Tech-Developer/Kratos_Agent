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
        """Returns the native Gemini Live tools declaration list."""
        start_task_fn = types.FunctionDeclaration(
            name="start_agent_task",
            description=(
                "Send an autonomous task to the Kratos agent brain for execution on the user's computer. "
                "ALWAYS call this when the user wants to: open/close/launch any application (YouTube, Chrome, VS Code, Terminal, etc.), "
                "browse/navigate/search/click/type on websites, play/pause/download/stream media or videos, "
                "create/modify/delete/read/write files or code, run/execute/test/build/deploy/install commands or programs, "
                "inspect/debug/fix/analyze projects or errors, automate workflows, or perform ANY computer action. "
                "This includes requests in any language (Tamil, Hindi, English, mixed). "
                "You MUST call this instead of refusing or claiming inability. Kratos has full computer control. "
                "Include a concise visual_context summary if the task relates to what you see on their screen or camera."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "task_description": types.Schema(
                        type="STRING",
                        description="Clear, actionable description of what Kratos should do on the computer. Translate non-English requests into English for the task description.",
                    ),
                    "visual_context": types.Schema(
                        type="STRING",
                        description="Optional concise summary of relevant screen or camera details (e.g. error trace, file name, UI issue).",
                    ),
                    "priority": types.Schema(
                        type="STRING",
                        description="Task priority: 'normal' or 'high'.",
                    ),
                },
                required=["task_description"],
            ),
        )

        capture_screen_fn = types.FunctionDeclaration(
            name="capture_screen_context",
            description=(
                "Capture a fresh screenshot of the user's desktop screen immediately. "
                "Call this whenever the user says 'look at this', 'what is this error', 'explain what I am seeing', "
                "'fix this error', or refers to visual content on their screen. "
                "The screen frame will be streamed into your visual perception so you can inspect it."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "reason": types.Schema(
                        type="STRING",
                        description="Brief explanation of why screen capture is needed (e.g., 'Inspecting compiler error', 'Viewing web page layout').",
                    ),
                },
            ),
        )

        cancel_task_fn = types.FunctionDeclaration(
            name="cancel_active_task",
            description="Cancel the currently running Kratos task. Call this when the user says stop, cancel, abort, or never mind.",
            parameters=types.Schema(
                type="OBJECT",
                properties={},
            ),
        )

        get_status_fn = types.FunctionDeclaration(
            name="get_task_status",
            description="Get the current status, plan, and progress of the active Kratos task. Call this when the user asks what you are currently doing.",
            parameters=types.Schema(
                type="OBJECT",
                properties={},
            ),
        )
        
        report_visual_status_fn = types.FunctionDeclaration(
            name="report_visual_status",
            description=(
                "Send real-time visual feedback to Kratos while it is executing a task in the background. "
                "Call this proactively when you observe the screen change (e.g. 'YouTube has opened', 'an error popped up', 'the video is playing'). "
                "This helps Kratos know if its actions succeeded."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "visual_summary": types.Schema(
                        type="STRING",
                        description="A clear description of what you currently see on the screen.",
                    ),
                },
                required=["visual_summary"],
            ),
        )

        return [
            types.Tool(
                function_declarations=[
                    start_task_fn,
                    capture_screen_fn,
                    cancel_task_fn,
                    get_status_fn,
                    report_visual_status_fn,
                ]
            )
        ]

    async def handle_tool_call(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatches Gemini Live tool calls to KratosBridge or screen capture."""
        logger.info(f"[LiveRouter] Received tool call: {name} with args: {args}")

        if name == "start_agent_task":
            desc = str(args.get("task_description", "")).strip()
            visual_ctx = args.get("visual_context")
            if not desc:
                return {"status": "error", "message": "Missing task description."}
            return await self.bridge.submit_task(desc, visual_context=visual_ctx)

        elif name == "capture_screen_context":
            reason = str(args.get("reason", "User requested visual inspection")).strip()
            logger.info(f"[LiveRouter] Capturing screen on-demand. Reason: {reason}")
            if self.capture_screen_handler:
                try:
                    if inspect.iscoroutinefunction(self.capture_screen_handler):
                        res = await self.capture_screen_handler()
                    else:
                        res = self.capture_screen_handler()
                    if res is False or (isinstance(res, dict) and res.get("status") == "error"):
                        err_msg = res.get("message") or res.get("error") if isinstance(res, dict) else "Screen capture returned failure"
                        return {
                            "status": "error",
                            "error_type": "SCREEN_CAPTURE_FAILURE",
                            "message": f"Screen capture failed: {err_msg}",
                            "recoverable": True,
                        }
                    return {
                        "status": "success",
                        "message": "Desktop screen captured and streamed to your visual perception. You can now inspect and analyze what the user is seeing.",
                    }
                except Exception as e:
                    return {
                        "status": "error",
                        "error_type": "SCREEN_CAPTURE_FAILURE",
                        "message": f"Screen capture failed: {type(e).__name__}: {e}",
                        "recoverable": True,
                    }
            return {
                "status": "error",
                "error_type": "SCREEN_CAPTURE_UNAVAILABLE",
                "message": "Screen capture handler not configured.",
                "recoverable": False,
            }


        elif name == "cancel_active_task":
            return self.bridge.cancel_active_task()

        elif name == "get_task_status":
            return self.bridge.get_status()

        elif name == "report_visual_status":
            summary = str(args.get("visual_summary", "")).strip()
            if not summary:
                return {"status": "error", "message": "Missing visual summary."}
            logger.info(f"[LiveRouter] Injecting visual status into Kratos: {summary}")
            
            # Inject into the active Kratos runtime history so the loop sees it next turn
            from kratos_agent.core.runtime_contracts import ChatMessage
            if hasattr(self.bridge, "runtime") and hasattr(self.bridge.runtime, "_history"):
                self.bridge.runtime._history.append(ChatMessage("user", f"[VISUAL FEEDBACK FROM GEMINI]:\n{summary}"))
                return {"status": "success", "message": "Visual feedback delivered to Kratos."}
            return {"status": "error", "message": "Kratos runtime not active."}

        else:
            return {"status": "error", "message": f"Unknown tool: {name}"}

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
