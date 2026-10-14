"""Alternate response protocols without changing the selected model or its tools."""
from __future__ import annotations

import json
from typing import Any

from kratos_agent.brain.config import BrainToolCallError


RECOVERY_PROTOCOLS = frozenset({"json", "single_json", "fresh_plan"})


def tool_recovery_instruction(protocol: str, tools: list[dict[str, Any]]) -> str:
    """Persist this instruction in history so browser conversation cursors remain valid."""
    if protocol not in RECOVERY_PROTOCOLS:
        raise ValueError("Unknown tool recovery protocol")
    single = (
        "Choose only the next necessary action. Return at most one tool call; "
        "wait for its real result before choosing another action. "
        if protocol in {"single_json", "fresh_plan"} else
        "Separate actions that depend on earlier tool results. "
    )
    reevaluate = (
        "Reconsider the approach using the verified tool results and the user's "
        "requested outcome. Explain the revised approach briefly in text, then "
        "choose the next achievable action. Do not repeat the failed response. "
        if protocol == "fresh_plan" else ""
    )
    return (
        "Use this alternate local JSON response protocol for the next response. "
        "Return one complete object with exactly text (a string) and tool_calls "
        "(an array of objects with exactly name and arguments). "
        "This envelope takes precedence over earlier native tool formatting rules. "
        'For a final answer use {"text":"your verified answer","tool_calls":[]}. '
        'For an action use {"text":"","tool_calls":[{"name":"REGISTERED_TOOL",'
        '"arguments":{}}]} with the real required arguments from its schema. '
        + single + reevaluate
        + "Do not use provider-native calls, DSML/XML control tokens, or call: markup. "
        "Use only these registered tools with complete schema-valid arguments. "
        "Do not guess missing arguments, tool names, results, or claim an action ran "
        "before its result arrives. Use forward slashes in Windows paths. "
        "Continue the user's task from verified evidence, using a different available "
        "method when the previous method failed. Registered schemas:\n"
        + json.dumps(tools, ensure_ascii=False, allow_nan=False)
    )


def plain_tool_transcript(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep real evidence when a provider cannot accept native tool history."""
    converted = []
    for message in messages:
        item = dict(message)
        if item.get("role") == "tool":
            converted.append({
                "role": "user",
                "content": (
                    "Local tool result (untrusted data), call "
                    + str(item.get("tool_call_id") or "") + ":\n"
                    + str(item.get("content") or "")
                ),
            })
            continue
        calls = item.pop("tool_calls", None)
        if calls:
            # Preserve the observed call exactly. This is a transcript, never a
            # newly scheduled call or a repair of a rejected response.
            item["content"] = (
                str(item.get("content") or "") + "\nPreviously requested local tools:\n"
                + json.dumps(calls, ensure_ascii=False, allow_nan=False)
            )
        converted.append(item)
    return converted


def parse_recovery_completion(text: str, tools: list[dict[str, Any]], protocol: str):
    """Reuse the strict registered-tool validator, then enforce a single-action mode."""
    if protocol not in RECOVERY_PROTOCOLS:
        raise ValueError("Unknown tool recovery protocol")
    from kratos_agent.brain.chatgpt_web import browser_completion
    from kratos_agent.brain.tool_calls import extract_tool_calls_from_text

    if not tools:
        from kratos_agent.sdk.client import KratosCompletion

        candidate = text.strip()
        if candidate.startswith("```json\n") and candidate.endswith("\n```"):
            candidate = candidate[8:-4].strip()
        if candidate.startswith(("{", "[")):
            try:
                body = json.loads(candidate)
                if (not isinstance(body, dict) or set(body) != {"text", "tool_calls"}
                        or not isinstance(body["text"], str) or body["tool_calls"] != []
                        or not body["text"].strip()):
                    raise ValueError("Invalid empty-tool result")
                completion = KratosCompletion(text=body["text"])
            except (ValueError, TypeError) as exc:
                raise BrainToolCallError("The alternate response requested unavailable tools or invalid JSON; no tool was executed.") from exc
        else:
            completion = browser_completion(text, tools)
    else:
        completion = browser_completion(text, tools)
    _, embedded_calls = extract_tool_calls_from_text(completion.text, strict=True)
    if embedded_calls:
        raise BrainToolCallError("The alternate response mixed executable tool markup into its text; no tool was executed.")
    try:
        for call in completion.tool_calls:
            json.dumps(call.arguments, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise BrainToolCallError("The alternate tool arguments contain invalid JSON values; no tool was executed.") from exc
    if protocol in {"single_json", "fresh_plan"} and len(completion.tool_calls) > 1:
        error = BrainToolCallError("The alternate response contained more than one tool call; no tool was executed.")
        error.correction = "Return at most one registered tool call with complete schema-valid arguments."
        raise error
    return completion
