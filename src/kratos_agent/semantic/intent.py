from __future__ import annotations

from typing import Any

from .schemas import IntentType, MissionIntent


def _infer_intent_type(capability: str | None) -> IntentType:
    value = (capability or "").lower()
    if value.startswith("search"):
        return IntentType.SEARCH
    if value.startswith("browser."):
        return IntentType.BROWSER_OPERATION
    if value.startswith("whatsapp."):
        return IntentType.COMMUNICATION
    if value.startswith("filesystem."):
        return IntentType.FILE_OPERATION
    if value.startswith("app.") or value == "open_application":
        return IntentType.APPLICATION_OPERATION
    if value.startswith("code."):
        return IntentType.DEVELOPMENT
    if value.startswith("system.") or value == "terminal.execute":
        return IntentType.SYSTEM_OPERATION
    if "youtube" in value or "media" in value:
        return IntentType.MEDIA_OPERATION
    return IntentType.COMPUTER_ACTION


def mission_from_tool_call(args: dict[str, Any]) -> MissionIntent:
    mission = str(args.get("mission") or args.get("objective") or args.get("task_description") or "").strip()
    capability = args.get("capability") or args.get("action")
    return MissionIntent(
        goal=mission,
        intent_type=_infer_intent_type(capability),
        capability=str(capability).strip() if capability else None,
        arguments=dict(args.get("arguments") or args.get("parameters") or {}),
        constraints=dict(args.get("constraints") or {}),
        expected_result=dict(args.get("expected_state") or args.get("expected_result") or {}),
        visual_context=args.get("visual_context"),
        priority=str(args.get("priority") or "normal"),
    )
