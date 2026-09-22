"""Memory decay policies and reinforcement mechanisms."""
from __future__ import annotations
import time
from typing import List

from kratos_agent.memory.models import MemoryLayer, MemoryRecord

# Decay rates per day based on layer (§28)
DECAY_RATES = {
    MemoryLayer.SEMANTIC: 0.001,      # Very slow decay for stable facts
    MemoryLayer.PROCEDURAL: 0.005,    # Slow decay for workflows
    MemoryLayer.APPLICATION: 0.002,   # Very slow decay for app knowledge
    MemoryLayer.ERROR: 0.02,          # Medium decay for error/recovery
    MemoryLayer.EPISODIC: 0.05,       # Fast decay for temporary events
    MemoryLayer.WORKING: 0.50,        # Extremely fast decay for task working memory
}


def apply_decay(record: MemoryRecord, elapsed_days: float) -> float:
    """Applies decay to memory confidence and importance over time."""
    rate = DECAY_RATES.get(record.layer, 0.01)
    decay_factor = (1.0 - rate) ** elapsed_days
    record.confidence = max(0.05, record.confidence * decay_factor)
    record.importance = max(0.05, record.importance * decay_factor)
    return record.confidence


def reinforce_memory(record: MemoryRecord, success: bool = True, bonus: float = 0.1) -> None:
    """Reinforces memory on successful reuse or penalizes on failure (§29)."""
    now = time.time()
    record.recency = now
    record.frequency += 1

    if success:
        record.success_count += 1
        record.confidence = min(1.0, record.confidence + bonus)
        record.utility = min(1.0, record.utility + bonus)
    else:
        record.failure_count += 1
        record.confidence = max(0.05, record.confidence - (bonus * 1.5))
        record.utility = max(0.05, record.utility - (bonus * 1.5))
