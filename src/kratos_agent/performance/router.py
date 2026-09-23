"""High-speed RequestRouter for classifying tasks and enabling fast paths."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class RequestCategory(str, Enum):
    CHAT = "CHAT"
    CODE = "CODE"
    TOOL = "TOOL"
    FILE_OPERATION = "FILE_OPERATION"
    COMPUTER_USE = "COMPUTER_USE"
    BROWSER = "BROWSER"
    MEMORY_QUERY = "MEMORY_QUERY"
    COMPLEX_TASK = "COMPLEX_TASK"


@dataclass
class RouteDecision:
    category: RequestCategory
    is_fast_path: bool
    target_tool_categories: List[str]
    requires_planning: bool
    requires_memory: bool
    requires_observation: bool
    confidence: float
    direct_tool: Optional[str] = None
    direct_tool_args: Optional[Dict[str, Any]] = None


class RequestRouter:
    """Classifies user requests to bypass unnecessary planning, observation, or memory."""

    # Fast-path pattern matchers
    _URL_PATTERN = re.compile(r"^(https?://|www\.)[^\s]+", re.IGNORECASE)
    _VISION_QUERY_PATTERN = re.compile(
        r"^(what('?s| is)? (do you see|you see|on (my |the )?screen|on (my |the )?display|this error)|describe (the |my )?screen|look at (the |my )?screen)",
        re.IGNORECASE,
    )
    _MATH_PATTERN = re.compile(r"^(what is|calculate|solve|\b)\s*(\d+\s*[\+\-\*\/\^%]\s*\d+)", re.IGNORECASE)
    _GREETING_PATTERN = re.compile(r"^(hi|hello|hey|good morning|good evening|who are you|what can you do)(\s+[a-zA-Z0-9_-]+)?[\?!.]*$", re.IGNORECASE)
    _EXPLAIN_PATTERN = re.compile(r"^(explain|what is|how does|why is|define)\s+(?!chrome|browser|app|computer|file|git|terminal)", re.IGNORECASE)
    _CODE_GEN_PATTERN = re.compile(r"^(write|create|implement|show me)\s+(a |an )?([a-zA-Z0-9_\+#\.]+\s+)?(function|class|script|regex|snippet|code)", re.IGNORECASE)
    _SINGLE_TOOL_PATTERNS = [
        (re.compile(r"^(run|execute)\s+(pytest|tests?|python\s+.*|cargo\s+.*|npm\s+.*|uv\s+.*)$", re.IGNORECASE), "run_terminal_command"),
        (re.compile(r"^git\s+(status|diff|log|branch)$", re.IGNORECASE), "git_status"),
        (re.compile(r"^(list|show)\s+(files|directory|folder)$", re.IGNORECASE), "list_directory"),
    ]
    _BROWSER_PATTERNS = re.compile(r"\b(youtube|browser|website|walk\s*through|web|url|navigate)\b", re.IGNORECASE)
    _COMPUTER_PATTERNS = re.compile(r"\b(open|launch|click|type|scroll|press|window|desktop|app)\b", re.IGNORECASE)
    _MEMORY_PATTERNS = re.compile(r"\b(what do you remember|recall|my preference|saved memory|what is my name)\b", re.IGNORECASE)

    def classify(self, request: str, history: Optional[List[Any]] = None) -> RouteDecision:
        """Determines the optimal execution route for a request."""
        clean = request.strip()
        clean_lower = clean.lower()

        # 0a. Direct URL Navigation Fast Path (§22)
        if self._URL_PATTERN.match(clean):
            return RouteDecision(
                category=RequestCategory.BROWSER,
                is_fast_path=True,
                target_tool_categories=["BROWSER", "COMPUTER", "GENERAL"],
                requires_planning=False,
                requires_memory=False,
                requires_observation=True,
                confidence=0.98,
            )

        # 0b. Vision Fast Path ("what do you see", "look at screen") (§14)
        if self._VISION_QUERY_PATTERN.match(clean) or clean_lower in (
            "what do you see",
            "what you see in this screen",
            "what do you see on this screen",
            "what do you see in this screen",
            "describe screen",
            "describe the screen",
        ):
            return RouteDecision(
                category=RequestCategory.COMPUTER_USE,
                is_fast_path=True,
                target_tool_categories=["COMPUTER", "GENERAL"],
                requires_planning=False,
                requires_memory=False,
                requires_observation=True,
                confidence=0.98,
            )

        # 1. Trivial CHAT / Math fast path
        if self._GREETING_PATTERN.match(clean) or self._MATH_PATTERN.match(clean):
            return RouteDecision(
                category=RequestCategory.CHAT,
                is_fast_path=True,
                target_tool_categories=[],
                requires_planning=False,
                requires_memory=False,
                requires_observation=False,
                confidence=0.99,
            )


        # 2. Browser / YouTube / Web Navigation direct path (§18, §19, §22, §23)
        if self._BROWSER_PATTERNS.search(clean_lower):
            is_multi_step = any(word in clean_lower for word in [" and ", " then ", "after that", "workflow", "automate"])
            if is_multi_step:
                return RouteDecision(
                    category=RequestCategory.COMPLEX_TASK,
                    is_fast_path=False,
                    target_tool_categories=["BROWSER", "COMPUTER", "GENERAL", "SYSTEM"],
                    requires_planning=True,
                    requires_memory=False,
                    requires_observation=True,
                    confidence=0.85,
                )
            return RouteDecision(
                category=RequestCategory.BROWSER,
                is_fast_path=True,
                target_tool_categories=["BROWSER", "COMPUTER", "GENERAL"],
                requires_planning=False,
                requires_memory=False,
                requires_observation=True,
                confidence=0.95,
            )

        # 3. Simple Memory Query
        if self._MEMORY_PATTERNS.search(clean_lower):
            return RouteDecision(
                category=RequestCategory.MEMORY_QUERY,
                is_fast_path=True,
                target_tool_categories=["MEMORY", "GENERAL"],
                requires_planning=False,
                requires_memory=True,
                requires_observation=False,
                confidence=0.95,
            )

        # 4. Direct Single Tool Execution
        for pattern, tool_name in self._SINGLE_TOOL_PATTERNS:
            match = pattern.match(clean)
            if match:
                return RouteDecision(
                    category=RequestCategory.TOOL,
                    is_fast_path=True,
                    target_tool_categories=["CODE", "FILES", "SYSTEM", "GENERAL"],
                    requires_planning=False,
                    requires_memory=False,
                    requires_observation=False,
                    confidence=0.92,
                    direct_tool=tool_name,
                )

        # 5. Pure Code Generation / Explanation
        if self._CODE_GEN_PATTERN.match(clean) or (self._EXPLAIN_PATTERN.match(clean) and not self._COMPUTER_PATTERNS.search(clean_lower)):
            return RouteDecision(
                category=RequestCategory.CODE if self._CODE_GEN_PATTERN.match(clean) else RequestCategory.CHAT,
                is_fast_path=True,
                target_tool_categories=["CODE", "FILES", "GENERAL"],
                requires_planning=False,
                requires_memory=False,
                requires_observation=False,
                confidence=0.90,
            )

        # 6. Computer Use (GUI / Desktop)
        if self._COMPUTER_PATTERNS.search(clean_lower):
            is_multi_step = any(word in clean_lower for word in [" and ", " then ", "after that", "workflow", "automate"])
            return RouteDecision(
                category=RequestCategory.COMPLEX_TASK if is_multi_step else RequestCategory.COMPUTER_USE,
                is_fast_path=not is_multi_step,
                target_tool_categories=["COMPUTER", "BROWSER", "SYSTEM", "GENERAL"],
                requires_planning=is_multi_step,
                requires_memory=False,
                requires_observation=True,
                confidence=0.88,
            )

        # 6. Default: Multi-step / Complex Task
        return RouteDecision(
            category=RequestCategory.COMPLEX_TASK,
            is_fast_path=False,
            target_tool_categories=["GENERAL", "CODE", "FILES", "SYSTEM", "BROWSER", "COMPUTER", "MEMORY"],
            requires_planning=True,
            requires_memory=True,
            requires_observation=True,
            confidence=0.75,
        )


_router: Optional[RequestRouter] = None


def get_request_router() -> RequestRouter:
    global _router
    if _router is None:
        _router = RequestRouter()
    return _router
