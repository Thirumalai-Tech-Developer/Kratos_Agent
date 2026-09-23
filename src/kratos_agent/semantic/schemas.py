from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class IntentType(str, Enum):
    INFORMATION = "information"
    CONVERSATION = "conversation"
    COMPUTER_ACTION = "computer_action"
    MULTI_STEP_MISSION = "multi_step_mission"
    OBSERVATION = "observation"
    DEBUG = "debug"
    SEARCH = "search"
    FILE_OPERATION = "file_operation"
    APPLICATION_OPERATION = "application_operation"
    BROWSER_OPERATION = "browser_operation"
    COMMUNICATION = "communication"
    MEDIA_OPERATION = "media_operation"
    DEVELOPMENT = "development"
    SYSTEM_OPERATION = "system_operation"


@dataclass(slots=True)
class MissionIntent:
    intent_id: str = field(default_factory=lambda: f"INT-{uuid.uuid4().hex[:10].upper()}")
    goal: str = ""
    intent_type: IntentType = IntentType.COMPUTER_ACTION
    capability: Optional[str] = None
    arguments: Dict[str, Any] = field(default_factory=dict)
    constraints: Dict[str, Any] = field(default_factory=dict)
    expected_result: Dict[str, Any] = field(default_factory=dict)
    visual_context: Optional[str] = None
    priority: str = "normal"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "goal": self.goal,
            "intent_type": self.intent_type.value,
            "capability": self.capability,
            "arguments": self.arguments,
            "constraints": self.constraints,
            "expected_result": self.expected_result,
            "visual_context": self.visual_context,
            "priority": self.priority,
        }
