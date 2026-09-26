"""Memory deduplication, consolidation, and importance gating."""
from __future__ import annotations

import re

from kratos_agent.memory.models import MemoryLayer, MemoryRecord


def normalize_text(text: str) -> str:
    """Normalizes text for deduplication."""
    clean = re.sub(r"\s+", " ", text.strip().lower())
    clean = re.sub(r"[^\w\s]", "", clean)
    return clean


def should_store(record: MemoryRecord) -> bool:
    """Importance gate: determines if a memory candidate is worth persisting (§38)."""
    # Reject empty or very short facts
    if len(record.content.strip()) < 5:
        return False
    # Reject low importance or low confidence items
    if record.importance < 0.20 or record.confidence < 0.20:
        return False
    # Working memory is handled ephemerally, not persisted directly via consolidation
    if record.layer == MemoryLayer.WORKING:
        return False
    return True


def deduplicate_records(records: list[MemoryRecord]) -> list[MemoryRecord]:
    """Merges semantically identical memories into canonical records (§31)."""
    seen: dict[str, MemoryRecord] = {}

    for rec in records:
        norm = normalize_text(rec.content)
        if norm in seen:
            existing = seen[norm]
            # Merge: keep higher confidence and importance, increase frequency
            existing.frequency += rec.frequency
            existing.confidence = max(existing.confidence, rec.confidence)
            existing.importance = max(existing.importance, rec.importance)
            existing.recency = max(existing.recency, rec.recency)
            existing.success_count += rec.success_count
            existing.failure_count += rec.failure_count
        else:
            seen[norm] = rec

    return list(seen.values())


def consolidate_memories(records: list[MemoryRecord], min_confidence: float = 0.15) -> list[MemoryRecord]:
    """Consolidates memory store: deduplicates, removes stale/unreliable records (§32)."""
    valid = [r for r in records if r.confidence >= min_confidence]
    deduped = deduplicate_records(valid)
    return deduped
