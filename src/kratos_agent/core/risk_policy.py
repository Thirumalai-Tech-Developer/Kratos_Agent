"""Deterministic guardrails for actions with significant consequences."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from kratos_agent.core.runtime_contracts import ToolPermission, ToolSpec


@dataclass(frozen=True, slots=True)
class RiskDecision:
    category: str
    authorized: bool
    reason: str


_RISK_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("external communication or publication", ("send", "email", "message", "post", "publish", "submit", "share", "upload", "invite", "push")),
    ("destructive or bulk change", ("delete", "remove", "drop", "wipe", "format", "reset", "purge", "uninstall", "truncate", "destroy", "erase", "bulk", "recursive")),
    ("financial or booking action", ("purchase", "buy", "pay", "payment", "checkout", "transfer", "order", "book", "booking", "reserve", "subscribe", "charge")),
    ("account or security change", ("password", "credential", "account", "permission", "privilege", "security", "2fa", "mfa", "grant", "revoke", "token", "secret", "sudo", "admin", "elevate")),
)
_ELEVATED_INSTALL = re.compile(r"\b(sudo|admin|elevat\w*|system[- ]wide|global install|driver|firmware|service install)\b", re.I)
_TARGET_KEYS = re.compile(r"(to|recipient|target|url|uri|channel|path|file|account|user|project|repo|resource|item|booking|subscription|destination|branch|server|host|id)$", re.I)
_OMIT_TARGET_KEYS = {"body", "content", "text", "message", "prompt", "code", "script", "command_output"}


def assess_tool_risk(spec: ToolSpec, arguments: dict[str, Any], user_request: str) -> RiskDecision | None:
    """Return a decision for high-impact calls; `None` means ordinary risk.

    Authorization must appear in the user's own request and include both an
    action term and every concrete target supplied to the tool call.
    """
    action_text = f"{spec.name} {_argument_summary(arguments)}"
    hints = {str(key).lower(): value for key, value in (spec.annotations or {}).items()}
    destructive_hint = hints.get("destructivehint", hints.get("destructive_hint")) is True
    open_world_hint = hints.get("openworldhint", hints.get("open_world_hint")) is True
    if spec.permission == ToolPermission.READ and not destructive_hint:
        return None

    category = next(
        (label for label, terms in _RISK_TERMS if _contains_any(action_text, terms)),
        None,
    )
    if category is None and _ELEVATED_INSTALL.search(action_text):
        category = "elevated or system-wide installation"

    if destructive_hint and category is None:
        category = "destructive MCP action"
    elif open_world_hint and category is None:
        category = "external-world MCP action"

    if category is None:
        return None

    request = _normalize(user_request)
    action_terms = _terms_for_category(category)
    direct_action = _contains_any(request, action_terms)
    targets = _targets(arguments)
    target_matches = bool(targets) and all(_normalize(target) in request for target in targets)
    authorized = direct_action and target_matches
    if authorized:
        reason = f"user directly requested {category} and named the exact target(s)"
    else:
        missing = []
        if not direct_action:
            missing.append("the exact action")
        if not target_matches:
            missing.append("the exact target")
        reason = (
            f"{category} requires the user's direct request to name "
            + " and ".join(missing)
            + "; this tool call was not executed"
        )
    return RiskDecision(category, authorized, reason)


def _argument_summary(arguments: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, value in arguments.items():
        if key.lower() in _OMIT_TARGET_KEYS:
            continue
        parts.append(f"{key} {value}")
    return " ".join(parts)


def _targets(arguments: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for key, value in arguments.items():
        if key.lower() in _OMIT_TARGET_KEYS:
            continue
        normalized_key = key.lower().rstrip("s")
        if _TARGET_KEYS.search(normalized_key):
            result.extend(_flatten_strings(value))
        elif key.lower() == "command":
            result.extend(_command_targets(str(value)))
    return list(dict.fromkeys(item.strip() for item in result if item.strip()))


def _flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, dict):
        return [part for child in value.values() for part in _flatten_strings(child)]
    if isinstance(value, (list, tuple, set)):
        return [part for child in value for part in _flatten_strings(child)]
    if isinstance(value, (int, float)):
        return [str(value)]
    return []


def _command_targets(command: str) -> list[str]:
    """Extract concrete destinations from common shell operations."""
    targets: list[str] = []
    for match in re.finditer(r"(?i)(?:https?://)[^\s\"'<>]+", command):
        targets.append(match.group(0).rstrip(".,;:)]}"))
    for match in re.finditer(
        r"(?i)(?:-literalpath|-path|--path|--file|-target|-destination)\s+(\"[^\"]+\"|'[^']+'|[^\s;&|]+)",
        command,
    ):
        targets.append(match.group(1).strip("\"'"))
    push = re.search(r"(?i)\bgit\s+push(?:\s+--[\w=-]+)*\s+([^\s;&|]+)(?:\s+([^\s;&|]+))?", command)
    if push:
        targets.extend(item for item in push.groups() if item)
    destructive = re.search(
        r"(?i)(?:\brm\b|\bdel\b|\berase\b|\bremove-item\b|\bunlink\b|\brmdir\b|\brd\b)\s+(.+)$",
        command,
    )
    if destructive:
        tail = destructive.group(1)
        named_path = re.search(r"(?i)(?:-literalpath|-path)\s+(\"[^\"]+\"|'[^']+'|[^\s;&|]+)", tail)
        if named_path:
            targets.append(named_path.group(1).strip("\"'"))
        else:
            tokens = re.findall(r"\"[^\"]+\"|'[^']+'|[^\s;&|]+", tail)
            targets.extend(token.strip("\"'") for token in tokens if not token.startswith("-"))
    install = re.search(r"(?i)\b(?:install|upgrade)\s+(?:--\w+\s+)*([@\w./-]+)", command)
    if install:
        targets.append(install.group(1))
    return [target for target in targets if target]


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    searchable = re.sub(r"[_-]+", " ", text)
    return any(re.search(rf"(?<![\w]){re.escape(term)}(?![\w])", searchable, re.I) for term in terms)


def _terms_for_category(category: str) -> tuple[str, ...]:
    if category.startswith("external communication"):
        return ("send", "post", "publish", "submit", "share", "upload", "invite", "push", "notify")
    if category.startswith("destructive"):
        return ("delete", "remove", "drop", "wipe", "format", "reset", "purge", "uninstall", "truncate", "destroy", "erase")
    if category.startswith("financial"):
        return ("purchase", "buy", "pay", "checkout", "transfer", "order", "book", "reserve", "subscribe", "charge")
    if category.startswith("account"):
        return ("change", "update", "set", "reset", "grant", "revoke", "enable", "disable", "rotate", "install", "uninstall")
    if category == "elevated or system-wide installation":
        return ("install", "upgrade", "remove", "uninstall")
    return (
        "send", "post", "publish", "submit", "share", "upload", "create", "update",
        "delete", "remove", "purchase", "buy", "pay", "book", "reserve", "transfer",
        "notify", "invite", "add",
    )


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().strip("`\"'.,;:()[]{}")).casefold()
