"""Semantic intent parsing for media, browser, and video playback commands (§13, §14, §15)."""
from __future__ import annotations
import re
from typing import Any, Dict


def parse_media_intent(text: str) -> Dict[str, Any]:
    """Parses natural language user commands into structured intent, platform, and clean query (§13, §14).
    
    Examples:
    - 'can you open youtube and god of wAR Walkthrough' -> intent: 'play_video', query: 'god of war walkthrough'
    - 'can you open youtube and play god of war walkthrough' -> intent: 'play_video', query: 'god of war walkthrough'
    - 'open youtube and play god of war walkthrough' -> intent: 'play_video', query: 'god of war walkthrough'
    - 'play god of war walkthrough on youtube' -> intent: 'play_video', query: 'god of war walkthrough'
    - 'search god of war walkthrough on youtube' -> intent: 'search_video', query: 'god of war walkthrough'
    - 'open youtube' -> intent: 'open_youtube', query: ''
    - 'pause' -> intent: 'pause_video', query: ''
    - 'resume' -> intent: 'resume_video', query: ''
    - 'standby' -> intent: 'standby', query: ''
    """
    raw = text.strip()
    clean = raw.lower()

    # 1. Strip conversational / polite prefixes
    stripped = re.sub(
        r"^(can you|could you|please|would you mind|i want to|i want you to)\s+",
        "",
        clean,
        flags=re.IGNORECASE,
    ).strip()

    # 2. Check for state-aware control commands
    if stripped in ("pause", "pause it", "pause video", "pause the video"):
        return {"intent": "pause_video", "platform": "youtube", "query": "", "raw": text}
    if stripped in ("resume", "resume it", "play it", "resume video", "resume the video", "unpause"):
        return {"intent": "resume_video", "platform": "youtube", "query": "", "raw": text}
    if stripped in ("standby", "stand by", "wait", "hold on"):
        return {"intent": "standby", "platform": "youtube", "query": "", "raw": text}

    # 3. Check for pure "open youtube"
    if stripped in ("open youtube", "open youtube.com", "go to youtube", "youtube", "navigate to youtube"):
        return {"intent": "open_youtube", "platform": "youtube", "query": "", "raw": text}

    # 4. Check for compound "open youtube and ..." (§27)
    m_compound = re.match(
        r"^(?:open youtube and\s+|go to youtube and\s+|navigate to youtube and\s+)(?:play\s+|search for\s+|search\s+|watch\s+|find and play\s+)?(.*)$",
        stripped,
    )
    if m_compound:
        query = m_compound.group(1).strip()
        query = re.sub(r"\s+on youtube$", "", query).strip()
        if query:
            return {
                "intent": "compound_browser_task",
                "platform": "youtube",
                "query": query,
                "raw": text,
                "actions": [
                    {"type": "open", "target": "https://www.youtube.com"},
                    {"type": "youtube_search", "query": query},
                    {"type": "youtube_play"},
                ],
            }
        return {"intent": "open_youtube", "platform": "youtube", "query": "", "raw": text}

    # 5. Check for explicit search
    m_search = re.match(
        r"^(?:search for\s+|search\s+|find\s+)(.*?)(?:\s+on youtube)?$",
        stripped,
    )
    if m_search and not stripped.startswith(("play ", "find and play ")):
        query = m_search.group(1).strip()
        if query:
            return {"intent": "search_video", "platform": "youtube", "query": query, "raw": text}

    # 6. Check for play patterns (§27)
    m_play = re.match(
        r"^(?:play\s+|watch\s+|find and play\s+|youtube play\s+)(.*?)(?:\s+on youtube)?$",
        stripped,
    )
    if m_play:
        query = m_play.group(1).strip()
        if query:
            return {
                "intent": "compound_browser_task",
                "platform": "youtube",
                "query": query,
                "raw": text,
                "actions": [
                    {"type": "open", "target": "https://www.youtube.com"},
                    {"type": "youtube_search", "query": query},
                    {"type": "youtube_play"},
                ],
            }

    # 7. Check for general mention of youtube + walkthrough/game/video
    if "youtube" in stripped and any(kw in stripped for kw in ("walkthrough", "gameplay", "video", "trailer", "song", "music")):
        q = stripped.replace("youtube", "").replace("open", "").replace("and", "").replace("play", "").strip()
        if q:
            return {
                "intent": "compound_browser_task",
                "platform": "youtube",
                "query": q,
                "raw": text,
                "actions": [
                    {"type": "open", "target": "https://www.youtube.com"},
                    {"type": "youtube_search", "query": q},
                    {"type": "youtube_play"},
                ],
            }

    # 8. Check for walkthrough without explicit 'play' or 'youtube'
    if "walkthrough" in stripped or "gameplay" in stripped:
        q = stripped.replace("can you", "").replace("open", "").replace("play", "").strip()
        if q:
            return {
                "intent": "compound_browser_task",
                "platform": "youtube",
                "query": q,
                "raw": text,
                "actions": [
                    {"type": "open", "target": "https://www.youtube.com"},
                    {"type": "youtube_search", "query": q},
                    {"type": "youtube_play"},
                ],
            }

    # 9. WhatsApp Web intent detection (§10, §46)
    if "whatsapp" in stripped:
        return {
            "intent": "open_whatsapp",
            "platform": "whatsapp",
            "query": stripped,
            "raw": text,
            "actions": [{"type": "open", "target": "https://web.whatsapp.com"}],
        }

    return {"intent": "unknown", "platform": "unknown", "query": raw, "raw": text}


def should_reuse_browser_context(prev_task_target: Any, current_intent: Dict[str, Any]) -> bool:
    """Enforces Section 10: Determines whether the previous browser task and new command belong to the same context.
    
    Examples:
    - Previous: YouTube, New: YouTube -> True (Reuse same tab PAGE-42)
    - Previous: YouTube, New: WhatsApp -> False (Different app/context: spin up new task context)
    """
    if not prev_task_target:
        return False
    if getattr(prev_task_target, "is_closed", None) and prev_task_target.is_closed():
        return False
    if not getattr(prev_task_target, "locked", False):
        return False

    prev_url = (getattr(prev_task_target, "current_url", "") or getattr(prev_task_target, "initial_url", "") or "").lower()
    curr_platform = current_intent.get("platform", "unknown")
    curr_intent = current_intent.get("intent", "unknown")

    # If new command is for YouTube and previous task tab was on YouTube -> reuse tab
    if curr_platform == "youtube" or curr_intent in ("play_video", "search_video", "pause_video", "resume_video", "standby"):
        if "youtube.com" in prev_url or getattr(prev_task_target, "tab_id", None):
            return True
        return False

    # If new command is WhatsApp or another distinct application, do NOT reuse YouTube tab state
    if curr_platform == "whatsapp":
        return "web.whatsapp.com" in prev_url

    # By default, do not blindly reuse
    return False
