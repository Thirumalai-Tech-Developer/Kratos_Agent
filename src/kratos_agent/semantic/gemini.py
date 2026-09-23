from __future__ import annotations

from typing import Any, Dict

from .intent import mission_from_tool_call
from .schemas import MissionIntent


class GeminiSemanticLayer:
    """Semantic contract adapter.

    The actual Gemini Live session owns model inference; this class only converts
    structured Gemini tool arguments into the canonical MissionIntent object.
    """

    def resolve(self, tool_args: Dict[str, Any]) -> MissionIntent:
        mission = mission_from_tool_call(tool_args)
        if not mission.goal:
            raise ValueError("Gemini returned an empty mission.")
        return mission
