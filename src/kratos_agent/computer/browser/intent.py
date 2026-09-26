"""Semantic intent parsing for browser/media/computer requests.

Fast paths are intentionally narrow: a shortcut may handle a pure single-purpose
request, but compound requests must remain visible to the general agent/Slave.
"""
from __future__ import annotations

import re
from typing import Any

_POLITE_PREFIX = re.compile(r"^(?:can you|could you|please|would you mind|i want to|i want you to)\s+", re.IGNORECASE)

def _strip_polite_prefix(text: str) -> str:
    return _POLITE_PREFIX.sub("", text.strip()).strip()

def _is_compound_text(text: str) -> bool:
    return bool(re.search(r"\b(?:and then|then|also|after that|before that|and)\b", text, re.IGNORECASE))

def is_pure_app_launch_request(text: str) -> bool:
    """True only for a simple open/launch/start request with no follow-up work."""
    stripped = _strip_polite_prefix(text).lower()
    m = re.fullmatch(r"(?:open|launch|start)\s+(.+)", stripped)
    if not m:
        return False
    target = m.group(1).strip()
    if not target or _is_compound_text(target):
        return False
    return not bool(re.search(
        r"\b(?:send|message|text|type|click|search|find|download|upload|play|watch|save|rename|close|reply|navigate|go to|with|into)\b",
        target,
        re.IGNORECASE,
    ))

def _extract_whatsapp_message(text: str) -> tuple[str, str] | None:
    stripped = _strip_polite_prefix(text)
    quoted = re.search(
        r'\b(?:send|message|text)\s+["“]([^"”]+)["”]\s+(?:message\s+)?to\s+["“]([^"”]+)["”]\s*$',
        stripped, re.IGNORECASE,
    )
    if quoted:
        return quoted.group(2).strip(), quoted.group(1).strip()

    # Natural speech often identifies the contact before the message:
    # "open whatsapp and chat with Thirumalai ... send hii to him"
    contact_hint = re.search(
        r'\b(?:chat|message|text)\s+with\s+(.+?)(?=\s+(?:may the contact|the contact|then|and then|send|message|text)\b|[.,!?]|$)',
        stripped, re.IGNORECASE,
    )
    hinted_contact = contact_hint.group(1).strip(' \'"“”') if contact_hint else None

    quoted_message = re.search(
        r'\b(?:send|message|text)\s+["“]([^"”]+)["”]\s+(?:message\s+)?to\s+(.+?)\s*$',
        stripped, re.IGNORECASE,
    )
    if quoted_message:
        target = quoted_message.group(2).strip(' \'"“”')
        if target.lower() in {"him", "her", "them"} and hinted_contact:
            target = hinted_contact
        return target, quoted_message.group(1).strip()

    generic = re.search(
        r'\b(?:send|message|text)\s+(.+?)\s+(?:message\s+)?to\s+(.+?)\s*$',
        stripped, re.IGNORECASE,
    )
    if generic:
        message = generic.group(1).strip(' \'\"“”')
        target = generic.group(2).strip(' \'\"“”')
        # Natural speech often adds a clarification after the real contact:
        # "send msg hi to thirumalai the contact may be in Tamil language".
        target = re.split(
            r'\s+(?:the\s+)?contact\b.*$',
            target,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip(' \'\"“”.,')
        message = re.sub(r'^(?:msg|message)\s+', '', message, flags=re.IGNORECASE).strip()
        if target.lower() in {"him", "her", "them"} and hinted_contact:
            target = hinted_contact
        if message and target:
            return target, message
    return None

def parse_media_intent(text: str) -> dict[str, Any]:
    """Parses narrow browser/media intents without swallowing compound computer tasks."""
    raw = text.strip()
    clean = raw.lower()
    stripped = _strip_polite_prefix(clean)

    if stripped in ("pause", "pause it", "pause video", "pause the video"):
        return {"intent": "pause_video", "platform": "youtube", "query": "", "raw": text}
    if stripped in ("resume", "resume it", "play it", "resume video", "resume the video", "unpause"):
        return {"intent": "resume_video", "platform": "youtube", "query": "", "raw": text}
    if stripped in ("standby", "stand by", "wait", "hold on"):
        return {"intent": "standby", "platform": "youtube", "query": "", "raw": text}
    if stripped in ("open youtube", "open youtube.com", "go to youtube", "youtube", "navigate to youtube"):
        return {"intent": "open_youtube", "platform": "youtube", "query": "", "raw": text}

    m_compound = re.match(
        r"^(?:open youtube and\s+|go to youtube and\s+|navigate to youtube and\s+)"
        r"(?:play\s+|search for\s+|search\s+|watch\s+|find and play\s+)?(.*)$", stripped,
    )
    if m_compound:
        query = re.sub(r"\s+on youtube$", "", m_compound.group(1).strip()).strip()
        if query:
            return {
                "intent": "compound_browser_task", "platform": "youtube", "query": query, "raw": text,
                "actions": [
                    {"type": "open", "target": "https://www.youtube.com"},
                    {"type": "youtube_search", "query": query},
                    {"type": "youtube_play"},
                ],
            }
        return {"intent": "open_youtube", "platform": "youtube", "query": "", "raw": text}

    m_search = re.match(r"^(?:search for\s+|search\s+|find\s+)(.*?)(?:\s+on youtube)?$", stripped)
    if m_search and not stripped.startswith(("play ", "find and play ")):
        query = m_search.group(1).strip()
        if query:
            return {"intent": "search_video", "platform": "youtube", "query": query, "raw": text}

    m_play = re.match(r"^(?:play\s+|watch\s+|find and play\s+|youtube play\s+)(.*?)(?:\s+on youtube)?$", stripped)
    if m_play:
        query = m_play.group(1).strip()
        if query:
            return {
                "intent": "compound_browser_task", "platform": "youtube", "query": query, "raw": text,
                "actions": [
                    {"type": "open", "target": "https://www.youtube.com"},
                    {"type": "youtube_search", "query": query},
                    {"type": "youtube_play"},
                ],
            }

    if "youtube" in stripped and any(kw in stripped for kw in ("walkthrough", "gameplay", "video", "trailer", "song", "music")):
        q = stripped.replace("youtube", "").replace("open", "").replace("and", "").replace("play", "").strip()
        if q:
            return {
                "intent": "compound_browser_task", "platform": "youtube", "query": q, "raw": text,
                "actions": [
                    {"type": "open", "target": "https://www.youtube.com"},
                    {"type": "youtube_search", "query": q},
                    {"type": "youtube_play"},
                ],
            }

    if "walkthrough" in stripped or "gameplay" in stripped:
        q = stripped.replace("can you", "").replace("open", "").replace("play", "").strip()
        if q:
            return {
                "intent": "compound_browser_task", "platform": "youtube", "query": q, "raw": text,
                "actions": [
                    {"type": "open", "target": "https://www.youtube.com"},
                    {"type": "youtube_search", "query": q},
                    {"type": "youtube_play"},
                ],
            }

    if "whatsapp" in stripped:
        parsed = _extract_whatsapp_message(raw)
        if parsed:
            contact, message = parsed
            return {
                "intent": "whatsapp_message", "platform": "whatsapp",
                "contact": contact, "message": message, "query": stripped, "raw": text,
                "actions": [
                    {"type": "open", "target": "https://web.whatsapp.com"},
                    {"type": "find_contact", "contact": contact},
                    {"type": "send_message", "message": message},
                    {"type": "verify_message", "message": message},
                ],
            }
        if stripped in (
            "whatsapp", "open whatsapp", "open whatsapp web", "go to whatsapp",
            "go to whatsapp web", "navigate to whatsapp", "open whatsapp.com",
        ):
            return {
                "intent": "open_whatsapp", "platform": "whatsapp", "query": "", "raw": text,
                "actions": [{"type": "open", "target": "https://web.whatsapp.com"}],
            }
    return {"intent": "unknown", "platform": "unknown", "query": raw, "raw": text}

def is_pure_browser_media_request(text: str) -> bool:
    intent = parse_media_intent(text).get("intent")
    return intent in {
        "open_youtube", "search_video", "compound_browser_task",
        "play_video", "pause_video", "resume_video", "standby",
    }

def should_reuse_browser_context(prev_task_target: Any, current_intent: dict[str, Any]) -> bool:
    if not prev_task_target:
        return False
    if getattr(prev_task_target, "is_closed", None) and prev_task_target.is_closed():
        return False
    if not getattr(prev_task_target, "locked", False):
        return False
    prev_url = (getattr(prev_task_target, "current_url", "") or getattr(prev_task_target, "initial_url", "") or "").lower()
    curr_platform = current_intent.get("platform", "unknown")
    curr_intent = current_intent.get("intent", "unknown")
    if curr_platform == "youtube" or curr_intent in ("play_video", "search_video", "pause_video", "resume_video", "standby"):
        return "youtube.com" in prev_url
    if curr_platform == "whatsapp":
        return "web.whatsapp.com" in prev_url
    return False
