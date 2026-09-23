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

    return {"intent": "unknown", "platform": "unknown", "query": raw, "raw": text}
