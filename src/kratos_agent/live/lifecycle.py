from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class LiveTurnState(str, Enum):
    USER_INPUT = "USER_INPUT"
    MODEL_THINKING = "MODEL_THINKING"
    TOOL_CALL = "TOOL_CALL"
    TOOL_EXECUTING = "TOOL_EXECUTING"
    TOOL_RESULT_SENT = "TOOL_RESULT_SENT"
    MODEL_FOLLOWUP = "MODEL_FOLLOWUP"
    USER_RESPONSE = "USER_RESPONSE"
    TURN_COMPLETE = "TURN_COMPLETE"


@dataclass
class LiveTurn:
    turn_id: str
    request_id: str
    state: LiveTurnState = LiveTurnState.USER_INPUT
    pending_tool_calls: set[str] = field(default_factory=set)
    completed_tool_calls: set[str] = field(default_factory=set)
    awaiting_model_followup: bool = False
    narration_pending: bool = False

    def begin_tool(self, call_id: str) -> None:
        self.pending_tool_calls.add(call_id)
        self.state = LiveTurnState.TOOL_EXECUTING

    def tool_result(self, call_id: str) -> None:
        self.pending_tool_calls.discard(call_id)
        self.completed_tool_calls.add(call_id)
        self.state = LiveTurnState.TOOL_RESULT_SENT
        self.awaiting_model_followup = True

    def can_finish(self) -> bool:
        return not self.pending_tool_calls and not self.awaiting_model_followup

    def model_followup(self) -> None:
        self.awaiting_model_followup = False
        self.state = LiveTurnState.MODEL_FOLLOWUP
