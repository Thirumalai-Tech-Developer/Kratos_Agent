"""Memory Maintenance and Memory Optimization Engine for Kratos Agent.

Coordinates multi-tier memory lifecycle operations:
1. Time-based decay computation across all memory layers (Working, Episodic, Error, Procedural, Semantic, Application)
2. Quality pruning: removes low-confidence, stale, expired, and orphaned memory records
3. Semantic deduplication & consolidation: merges redundant facts while preserving frequency and confidence
4. Cognitive memory store pruning: purges legacy working scratchpads and expired episodic logs
5. Session log optimization: truncates bloated terminal outputs and old tool traces
6. Database defragmentation & vacuuming: reclaims disk space in Cloudflare D1 / local SQLite mirror
7. Hot-cache compaction: purges expired and oversized memory cache entries
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from kratos_agent.core.cognitive_memory import cognitive_memory
from kratos_agent.core.compactor import ConversationCompactor
from kratos_agent.core.d1_client import d1_db
from kratos_agent.memory.consolidation import consolidate_memories
from kratos_agent.memory.decay import apply_decay
from kratos_agent.memory.models import MemoryLayer, MemoryRecord, MemoryScope
from kratos_agent.memory.store import MemoryStore

logger = logging.getLogger(__name__)


class MemoryMaintenanceReport:
    """Detailed diagnostic report of a memory optimization run."""

    def __init__(self) -> None:
        self.timestamp: float = time.time()
        self.decayed_count: int = 0
        self.pruned_records_count: int = 0
        self.deduplicated_count: int = 0
        self.retained_records_count: int = 0
        self.cognitive_records_pruned: int = 0
        self.synced_to_v2_count: int = 0
        self.synced_to_cognitive_count: int = 0
        self.sessions_optimized_count: int = 0
        self.tool_outputs_trimmed: int = 0
        self.db_reclaimed_bytes: int = 0
        self.cache_entries_cleared: int = 0
        self.health_score: float = 100.0
        self.health_status: str = "OPTIMAL"
        self.layer_counts: dict[str, int] = {}
        self.duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "duration_ms": round(self.duration_ms, 2),
            "decayed_count": self.decayed_count,
            "pruned_records_count": self.pruned_records_count,
            "deduplicated_count": self.deduplicated_count,
            "retained_records_count": self.retained_records_count,
            "cognitive_records_pruned": self.cognitive_records_pruned,
            "synced_to_v2_count": self.synced_to_v2_count,
            "synced_to_cognitive_count": self.synced_to_cognitive_count,
            "sessions_optimized_count": self.sessions_optimized_count,
            "tool_outputs_trimmed": self.tool_outputs_trimmed,
            "db_reclaimed_bytes": self.db_reclaimed_bytes,
            "cache_entries_cleared": self.cache_entries_cleared,
            "health_score": self.health_score,
            "health_status": self.health_status,
            "layer_counts": self.layer_counts,
        }


class MemoryOptimizer:
    """Comprehensive engine for maintaining and optimizing all tiers of Kratos memory."""

    def __init__(self, memory_store: MemoryStore | None = None) -> None:
        self.store = memory_store or MemoryStore()
        self.compactor = ConversationCompactor()

    def sync_tiers(self, report: MemoryMaintenanceReport | None = None) -> tuple[int, int]:
        """Bidirectionally synchronizes primary semantic & procedural knowledge between Cognitive Store and Memory V2."""
        synced_to_v2 = 0
        synced_to_cog = 0

        # 1. Cognitive Memory -> Memory V2 Store
        try:
            cog_records = cognitive_memory.recall(memory_type=None, limit=100)
            existing_contents = {r.content.strip().lower() for r in self.store.list_records()}
            existing_keys = {str(r.metadata.get("key", "")).strip().lower() for r in self.store.list_records() if r.metadata.get("key")}

            for cr in cog_records:
                m_type = cr.get("memory_type", "")
                if m_type not in ("semantic", "procedural"):
                    continue
                content = cr.get("content", "").strip()
                key = cr.get("key", "").strip()
                if not content or len(content) < 5:
                    continue

                if content.lower() in existing_contents or (key and key.lower() in existing_keys):
                    continue

                layer = MemoryLayer.SEMANTIC if m_type == "semantic" else MemoryLayer.PROCEDURAL
                new_rec = MemoryRecord(
                    content=content,
                    layer=layer,
                    scope=MemoryScope.GLOBAL,
                    confidence=0.88,
                    importance=0.80,
                    metadata={"key": key, "source": "cognitive_sync"},
                    tags=["cognitive_sync", m_type],
                )
                self.store.add(new_rec)
                existing_contents.add(content.lower())
                if key:
                    existing_keys.add(key.lower())
                synced_to_v2 += 1
        except Exception as exc:
            logger.debug("Cognitive -> V2 sync error: %s", exc)

        # 2. Memory V2 Store -> Cognitive Memory
        try:
            v2_candidates = [
                r for r in self.store.list_records()
                if r.confidence >= 0.75 and r.importance >= 0.50
                and r.layer in (MemoryLayer.SEMANTIC, MemoryLayer.PROCEDURAL)
            ]
            cog_existing_keys = {
                str(r.get("key", "")).strip().lower()
                for r in cognitive_memory.recall(memory_type=None, limit=100)
                if r.get("key")
            }

            for v2_rec in v2_candidates:
                m_type = "semantic" if v2_rec.layer == MemoryLayer.SEMANTIC else "procedural"
                key = v2_rec.metadata.get("key") or f"{m_type}_{v2_rec.id}"
                if str(key).strip().lower() in cog_existing_keys:
                    continue

                cognitive_memory.store(
                    memory_type=m_type,
                    key=str(key),
                    content=v2_rec.content,
                    metadata={"source": "v2_sync", "confidence": v2_rec.confidence, "importance": v2_rec.importance},
                )
                cog_existing_keys.add(str(key).strip().lower())
                synced_to_cog += 1
        except Exception as exc:
            logger.debug("V2 -> Cognitive sync error: %s", exc)

        if report:
            report.synced_to_v2_count = synced_to_v2
            report.synced_to_cognitive_count = synced_to_cog

        return synced_to_v2, synced_to_cog

    def run_maintenance(
        self,
        min_confidence: float = 0.15,
        max_episodic_age_days: float = 30.0,
        max_working_age_days: float = 2.0,
        optimize_db: bool = True,
        optimize_sessions: bool = True,
        sync_cross_tier: bool = True,
    ) -> MemoryMaintenanceReport:
        """Executes full memory maintenance, decay calculations, deduplication, and compaction."""
        start_time = time.monotonic()
        report = MemoryMaintenanceReport()
        now = time.time()

        # ── Cross-Tier Memory Synchronization ─────────────────────────────
        if sync_cross_tier:
            self.sync_tiers(report)

        # ── 1. Apply Time-Based Decay Across Memory V2 Records ─────────────
        with self.store._lock:
            all_records = list(self.store._records.values())
            initial_count = len(all_records)

            for rec in all_records:
                # Calculate elapsed days since last recency update
                ref_time = rec.recency or rec.created_at or now
                elapsed_days = max(0.0, (now - ref_time) / 86400.0)

                if elapsed_days >= 0.05:  # At least ~1 hour elapsed
                    old_conf = rec.confidence
                    apply_decay(rec, elapsed_days)
                    rec.recency = now
                    if abs(old_conf - rec.confidence) > 0.001:
                        report.decayed_count += 1

            # ── 2. Filter & Prune Low-Confidence or Expired Records ────────
            surviving: list[MemoryRecord] = []
            for rec in all_records:
                # Do not prune pinned or permanent facts
                is_permanent = "permanent" in rec.tags or rec.metadata.get("pinned", False)

                # Age limit for ephemeral layers
                ref_time = rec.created_at or rec.recency or now
                age_days = (now - ref_time) / 86400.0

                if not is_permanent:
                    if rec.layer == MemoryLayer.WORKING and age_days > max_working_age_days:
                        report.pruned_records_count += 1
                        continue
                    if rec.layer == MemoryLayer.EPISODIC and age_days > max_episodic_age_days:
                        report.pruned_records_count += 1
                        continue
                    if rec.confidence < min_confidence or rec.importance < 0.10:
                        report.pruned_records_count += 1
                        continue

                surviving.append(rec)

            # ── 3. Deduplicate and Consolidate Memory Records ──────────────
            consolidated = consolidate_memories(surviving, min_confidence=min_confidence)
            report.deduplicated_count = len(surviving) - len(consolidated)
            report.retained_records_count = len(consolidated)

            # Update store internal state
            self.store._records = {r.id: r for r in consolidated}
            report.cache_entries_cleared = len(self.store._hot_cache)
            self.store.invalidate_cache()
            self.store.save()

            # Record layer distribution
            for r in consolidated:
                layer_name = r.layer.value if hasattr(r.layer, "value") else str(r.layer)
                report.layer_counts[layer_name] = report.layer_counts.get(layer_name, 0) + 1

        # ── 4. Maintain Cognitive Memory Store (Working/Episodic Pruning) ──
        try:
            # Clear old working scratchpads and expired episodic entries
            # Keep semantic facts and procedural playbooks intact
            cutoff_date = time.strftime(
                "%Y-%m-%d %H:%M:%S",
                time.localtime(now - (max_episodic_age_days * 86400.0)),
            )
            # Prune episodic older than cutoff in D1/SQLite
            d1_db.execute(
                "DELETE FROM cognitive_memory WHERE memory_type = 'episodic' AND updated_at < ?",
                [cutoff_date],
            )
            # Prune completed working scratchpads older than 2 days
            working_cutoff = time.strftime(
                "%Y-%m-%d %H:%M:%S",
                time.localtime(now - (max_working_age_days * 86400.0)),
            )
            d1_db.execute(
                "DELETE FROM cognitive_memory WHERE memory_type = 'working' AND updated_at < ?",
                [working_cutoff],
            )

            # Clean disk mirrors
            for m_type in ("working", "episodic"):
                disk_file = cognitive_memory.storage_dir / f"{m_type}.json"
                if disk_file.exists():
                    try:
                        items = json.loads(disk_file.read_text(encoding="utf-8"))
                        filtered = []
                        for item in items:
                            ts = item.get("updated_at") or item.get("created_at") or ""
                            limit_cutoff = working_cutoff if m_type == "working" else cutoff_date
                            if ts and ts < limit_cutoff:
                                report.cognitive_records_pruned += 1
                            else:
                                filtered.append(item)
                        disk_file.write_text(json.dumps(filtered, indent=2, ensure_ascii=False), encoding="utf-8")
                    except Exception as exc:
                        logger.debug("Cognitive disk mirror prune error: %s", exc)
        except Exception as exc:
            logger.debug("Cognitive memory maintenance error: %s", exc)

        # ── 5. Session History Trimming & Tool Output Pruning ──────────────
        if optimize_sessions:
            sessions_dir = Path.cwd() / ".kratos" / "sessions"
            if sessions_dir.exists():
                try:
                    for s_file in sessions_dir.glob("*.json"):
                        if s_file.name == "index.json":
                            continue
                        try:
                            s_data = json.loads(s_file.read_text(encoding="utf-8"))
                            modified = False
                            # Trim oversized command outputs in session executed_commands
                            for cmd in s_data.get("executed_commands", []):
                                out = str(cmd.get("output", ""))
                                if len(out) > 1000:
                                    cmd["output"] = self.compactor.prune_tool_output(out, max_chars=500)
                                    report.tool_outputs_trimmed += 1
                                    modified = True

                            # Trim oversized tool calls in turns
                            for turn in s_data.get("turns", []):
                                for tc in turn.get("tool_calls", []):
                                    resp = str(tc.get("result", ""))
                                    if len(resp) > 1200:
                                        tc["result"] = self.compactor.prune_tool_output(resp, max_chars=600)
                                        report.tool_outputs_trimmed += 1
                                        modified = True

                            if modified:
                                s_file.write_text(json.dumps(s_data, indent=2, ensure_ascii=False), encoding="utf-8")
                                report.sessions_optimized_count += 1
                        except Exception as exc:
                            logger.debug("Session file optimization error for %s: %s", s_file, exc)
                except Exception as exc:
                    logger.debug("Session directory maintenance error: %s", exc)

        # ── 6. Database Vacuum & Index Optimization ───────────────────────
        if optimize_db:
            try:
                db_stats = d1_db.optimize()
                report.db_reclaimed_bytes = db_stats.get("reclaimed_bytes", 0)
            except Exception as exc:
                logger.debug("Database vacuum error: %s", exc)

        # ── 7. Prune Expired Agentic Event Logs ────────────────────────────
        try:
            events_cutoff = time.strftime(
                "%Y-%m-%d %H:%M:%S",
                time.localtime(now - (30.0 * 86400.0)),
            )
            d1_db.execute("DELETE FROM agentic_events WHERE timestamp < ?", [events_cutoff])
        except Exception as exc:
            logger.debug("Agentic events prune error: %s", exc)

        # ── 8. Calculate Overall Memory Health Metrics ──────────────────────
        health = self.store.get_health_metrics()
        report.health_score = health.get("health_score", 100.0)
        report.health_status = health.get("health_status", "OPTIMAL")

        report.duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "[MemoryOptimizer] Maintenance complete in %.1fms: decayed=%d, pruned=%d, deduped=%d, retained=%d, synced_v2=%d, synced_cog=%d, health=%.1f%% (%s), db_reclaimed=%d bytes",
            report.duration_ms,
            report.decayed_count,
            report.pruned_records_count,
            report.deduplicated_count,
            report.retained_records_count,
            report.synced_to_v2_count,
            report.synced_to_cognitive_count,
            report.health_score,
            report.health_status,
            report.db_reclaimed_bytes,
        )
        return report


_global_optimizer: MemoryOptimizer | None = None


def get_memory_optimizer() -> MemoryOptimizer:
    """Returns the singleton MemoryOptimizer instance."""
    global _global_optimizer
    if _global_optimizer is None:
        _global_optimizer = MemoryOptimizer()
    return _global_optimizer
