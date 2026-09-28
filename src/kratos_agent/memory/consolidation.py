"""Memory deduplication, consolidation, and importance gating."""
from __future__ import annotations

import re

from kratos_agent.memory.models import MemoryLayer, MemoryRecord

STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by",
    "can", "did", "do", "does", "doing", "down", "during", "each", "few", "for", "from",
    "further", "had", "has", "have", "having", "he", "her", "here", "hers", "herself", "him", "himself",
    "his", "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just", "me", "more", "most",
    "my", "myself", "no", "nor", "not", "now", "of", "off", "on", "once", "only", "or", "other",
    "our", "ours", "ourselves", "out", "over", "own", "same", "she", "should", "so", "some", "such",
    "than", "that", "the", "their", "theirs", "them", "themselves", "then", "there", "these", "they",
    "this", "those", "through", "to", "too", "under", "until", "up", "very", "was", "we", "were",
    "what", "when", "where", "which", "while", "who", "whom", "why", "with", "you", "your", "yours"
}


def normalize_text(text: str) -> str:
    """Normalizes text for deduplication."""
    clean = re.sub(r"\s+", " ", text.strip().lower())
    clean = re.sub(r"[^\w\s]", "", clean)
    return clean


def stem_token(word: str) -> str:
    """Lightweight rule-based stemmer for common English suffixes."""
    w = word.strip().lower()
    if len(w) > 4:
        if w.endswith("ies"):
            return w[:-3] + "y"
        if w.endswith("ing"):
            return w[:-3]
        if w.endswith("ed"):
            return w[:-2]
        if w.endswith("ly"):
            return w[:-2]
        if w.endswith("es"):
            return w[:-2]
        if w.endswith("s") and not w.endswith("ss"):
            return w[:-1]
    return w


def extract_content_tokens(text: str) -> set[str]:
    """Extracts informative content words from text, excluding stopwords with stemming."""
    norm = normalize_text(text)
    return {stem_token(w) for w in norm.split() if w not in STOPWORDS and len(w) > 1}


def compute_token_similarity(tokens_a: set[str], tokens_b: set[str]) -> float:
    """Computes Dice similarity coefficient between two sets of content tokens."""
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = len(tokens_a & tokens_b)
    return (2.0 * intersection) / (len(tokens_a) + len(tokens_b))


def merge_records(canonical: MemoryRecord, duplicate: MemoryRecord) -> MemoryRecord:
    """Merges a duplicate record into a canonical record while preserving frequency and confidence."""
    # Prefer longer or higher-confidence content
    if len(duplicate.content) > len(canonical.content) and duplicate.confidence >= canonical.confidence:
        canonical.content = duplicate.content
    canonical.frequency += duplicate.frequency
    canonical.confidence = max(canonical.confidence, duplicate.confidence)
    canonical.importance = max(canonical.importance, duplicate.importance)
    canonical.recency = max(canonical.recency, duplicate.recency)
    canonical.last_used = max(canonical.last_used, duplicate.last_used)
    canonical.success_count += duplicate.success_count
    canonical.failure_count += duplicate.failure_count

    # Union tags
    if duplicate.tags:
        merged_tags = list(dict.fromkeys(canonical.tags + duplicate.tags))
        canonical.tags = merged_tags

    # Merge metadata
    if duplicate.metadata:
        for k, v in duplicate.metadata.items():
            if k not in canonical.metadata:
                canonical.metadata[k] = v

    return canonical


def should_store(record: MemoryRecord) -> bool:
    """Importance gate: determines if a memory candidate is worth persisting (§38)."""
    # Permanent or pinned records always pass
    if "permanent" in record.tags or record.metadata.get("pinned", False):
        return True
    # Reject empty or very short facts
    if len(record.content.strip()) < 5:
        return False
    # Reject low importance or low confidence items
    if record.importance < 0.15 or record.confidence < 0.15:
        return False
    # Working memory is handled ephemerally, not persisted directly via consolidation
    if record.layer == MemoryLayer.WORKING:
        return False
    return True


def deduplicate_records(records: list[MemoryRecord], fuzzy_threshold: float = 0.80) -> list[MemoryRecord]:
    """Merges semantically identical memories into canonical records (§31)."""
    # 1. Exact string deduplication (fast pass)
    seen: dict[str, MemoryRecord] = {}
    for rec in records:
        norm = normalize_text(rec.content)
        if norm in seen:
            merge_records(seen[norm], rec)
        else:
            seen[norm] = rec

    candidates = list(seen.values())
    if len(candidates) <= 1:
        return candidates

    # 2. Fuzzy semantic deduplication & key-collision merging
    token_map = {r.id: extract_content_tokens(r.content) for r in candidates}
    merged_ids: set[str] = set()
    result: list[MemoryRecord] = []

    for i, rec1 in enumerate(candidates):
        if rec1.id in merged_ids:
            continue
        tokens1 = token_map.get(rec1.id, set())

        for j in range(i + 1, len(candidates)):
            rec2 = candidates[j]
            if rec2.id in merged_ids:
                continue
            if rec1.layer != rec2.layer:
                continue

            # Check key collision
            key1 = rec1.metadata.get("key")
            key2 = rec2.metadata.get("key")
            if key1 and key2 and str(key1).strip().lower() == str(key2).strip().lower():
                merge_records(rec1, rec2)
                merged_ids.add(rec2.id)
                continue

            # Check token similarity
            tokens2 = token_map.get(rec2.id, set())
            if len(tokens1) >= 2 and len(tokens2) >= 2:
                sim = compute_token_similarity(tokens1, tokens2)
                if sim >= fuzzy_threshold:
                    merge_records(rec1, rec2)
                    merged_ids.add(rec2.id)

        result.append(rec1)

    return result


def consolidate_memories(records: list[MemoryRecord], min_confidence: float = 0.15) -> list[MemoryRecord]:
    """Consolidates memory store: deduplicates, removes stale/unreliable records (§32)."""
    valid = [r for r in records if r.confidence >= min_confidence]
    deduped = deduplicate_records(valid)
    return deduped
