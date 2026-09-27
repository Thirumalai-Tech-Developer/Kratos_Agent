"""Hybrid ranking engine for memory retrieval."""
from __future__ import annotations

import math
import time

from kratos_agent.memory.models import MemoryQuery, MemoryRecord, MemoryScope

DEFAULT_WEIGHTS = {
    "similarity": 0.30,
    "relevance": 0.25,
    "importance": 0.15,
    "confidence": 0.15,
    "recency": 0.05,
    "frequency": 0.05,
    "context_match": 0.05,
}

# Scope priority order (§41): TASK -> SESSION -> PROJECT -> APPLICATION -> USER -> GLOBAL
SCOPE_PRIORITY = {
    MemoryScope.TASK: 1.0,
    MemoryScope.SESSION: 0.9,
    MemoryScope.PROJECT: 0.8,
    MemoryScope.APPLICATION: 0.7,
    MemoryScope.USER: 0.6,
    MemoryScope.GLOBAL: 0.5,
    MemoryScope.WORKFLOW: 0.75,
}


from kratos_agent.memory.consolidation import STOPWORDS


def _compute_text_overlap(query_text: str, content: str) -> float:
    """Computes normalized word overlap similarity with stopword filtering and phrase bonuses."""
    q_words = set(query_text.lower().split())
    c_words = set(content.lower().split())
    if not q_words or not c_words:
        return 0.0

    # Filter out stopwords for content-rich matching
    q_content = {w for w in q_words if w not in STOPWORDS and len(w) > 1}
    c_content = {w for w in c_words if w not in STOPWORDS and len(w) > 1}

    # If content words exist, compute overlap primarily on content words
    if q_content and c_content:
        overlap = len(q_content & c_content)
        base_score = overlap / max(len(q_content), 1)
    else:
        overlap = len(q_words & c_words)
        base_score = overlap / max(len(q_words), 1)

    # Phrase match bonus: if exact query substring appears in content
    clean_q = query_text.strip().lower()
    if len(clean_q) > 3 and clean_q in content.lower():
        base_score = min(1.0, base_score + 0.25)

    return base_score


def rank_memories(
    query: MemoryQuery,
    records: list[MemoryRecord],
    weights: dict[str, float] | None = None,
) -> list[tuple[MemoryRecord, float]]:
    """Ranks memory records using hybrid multi-factor scoring (§33)."""
    w = weights or DEFAULT_WEIGHTS
    now = time.time()
    results: list[tuple[MemoryRecord, float]] = []

    for rec in records:
        # Confidence threshold check (§30)
        if rec.confidence < query.min_confidence:
            continue

        # 1. Similarity (word overlap / token match + tag/key match)
        similarity = _compute_text_overlap(query.text, rec.content)
        q_tokens = {w for w in query.text.lower().split() if w not in STOPWORDS and len(w) > 1}
        if q_tokens:
            rec_tags = {str(t).lower() for t in rec.tags}
            rec_key = str(rec.metadata.get("key", "")).lower()
            if any(t in rec_tags or t in rec_key for t in q_tokens):
                similarity = min(1.0, similarity + 0.15)

        # 2. Task relevance
        relevance = 0.5
        if query.task:
            relevance = _compute_text_overlap(query.task, rec.content)
        elif similarity > 0.3:
            relevance = similarity

        # 3. Importance (0.0 to 1.0)
        importance = max(0.0, min(1.0, rec.importance))

        # 4. Confidence (0.0 to 1.0)
        confidence = max(0.0, min(1.0, rec.confidence))

        # 5. Recency: exponential decay over 30 days
        age_hours = (now - rec.recency) / 3600.0
        recency = math.exp(-0.001 * age_hours)

        # 6. Frequency: logarithmic scaling of access count
        frequency = min(1.0, math.log1p(rec.frequency) / 5.0)

        # 7. Context Match (application, project, platform, scope)
        context_match = 0.0
        matches = 0
        checks = 0

        if query.application and rec.metadata.get("application"):
            checks += 1
            if query.application.lower() == str(rec.metadata.get("application")).lower():
                matches += 1

        if query.project and rec.metadata.get("project"):
            checks += 1
            if query.project.lower() == str(rec.metadata.get("project")).lower():
                matches += 1

        if query.platform and rec.metadata.get("platform"):
            checks += 1
            if query.platform.lower() == str(rec.metadata.get("platform")).lower():
                matches += 1

        scope_boost = SCOPE_PRIORITY.get(rec.scope, 0.5)
        if checks > 0:
            context_match = (matches / checks) * 0.5 + scope_boost * 0.5
        else:
            context_match = scope_boost

        score = (
            similarity * w.get("similarity", 0.30)
            + relevance * w.get("relevance", 0.25)
            + importance * w.get("importance", 0.15)
            + confidence * w.get("confidence", 0.15)
            + recency * w.get("recency", 0.05)
            + frequency * w.get("frequency", 0.05)
            + context_match * w.get("context_match", 0.05)
        )

        results.append((rec, score))

    results.sort(key=lambda x: x[1], reverse=True)
    return results
