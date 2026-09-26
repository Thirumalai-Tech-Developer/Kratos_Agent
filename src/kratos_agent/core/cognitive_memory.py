"""
Cognitive Memory Architecture for Kratos Autonomous Agent.
Implements the 4-tier cognitive memory model:
  1. WORKING: Short-term scratchpad, active task objectives, file tracker, step-by-step reasoning notes.
  2. EPISODIC: Autobiographical history of past experiences, executed commands, tool traces, outcomes, lessons learned.
  3. SEMANTIC: Persistent facts, project conventions, architectural decisions, user preferences, domain knowledge.
  4. PROCEDURAL: "How-to" playbooks, skills, operational workflows, verification recipes, tool protocols.

Dual-Tier Storage:
  - Cloudflare D1 Serverless SQL / Local SQLite mirror via D1DatabaseClient
  - Local disk JSON backup in .kratos/memory/
"""
from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

import json
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any

from kratos_agent.core.d1_client import D1DatabaseClient, d1_db


class MemoryType(str, Enum):
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"

    @classmethod
    def from_string(cls, val: str) -> MemoryType:
        norm = val.lower().strip()
        for member in cls:
            if member.value == norm or norm.startswith(member.value[:4]):
                return member
        return cls.WORKING


class CognitiveMemoryStore:
    """Manages multi-tier cognitive memory storage, indexing, and context injection."""

    VALID_TYPES = {m.value for m in MemoryType}

    def __init__(self, db: D1DatabaseClient | None = None, storage_dir: Path | None = None):
        self.db = db or d1_db
        self.storage_dir = storage_dir or (Path.cwd() / ".kratos" / "memory")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_disk_structure()

    def _ensure_disk_structure(self) -> None:
        for m_type in self.VALID_TYPES:
            f = self.storage_dir / f"{m_type}.json"
            if not f.exists():
                try:
                    f.write_text("[]", encoding="utf-8")
                except Exception as exc:
                    logger.debug("Operation error suppressed: %s", exc)

    def store(
        self,
        memory_type: str | MemoryType,
        key: str,
        content: str,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Stores or updates a memory record in both D1/SQLite and disk mirror."""
        m_type = memory_type.value if isinstance(memory_type, MemoryType) else MemoryType.from_string(memory_type).value
        key_clean = key.strip()
        content_clean = content.strip()
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

        # 1. Query if an entry with this key & type exists to update it, or generate new id
        existing_id: str | None = None
        try:
            query = "SELECT id FROM cognitive_memory WHERE memory_type = ? AND key = ?"
            params: list[Any] = [m_type, key_clean]
            if session_id and m_type in ("working", "episodic"):
                query += " AND session_id = ?"
                params.append(session_id)
            rows = self.db.execute(query, params)
            if rows:
                existing_id = rows[0]["id"]
        except Exception as exc:
            logger.debug("Operation error suppressed: %s", exc)

        mem_id = existing_id or f"mem_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)

        record = {
            "id": mem_id,
            "session_id": session_id,
            "memory_type": m_type,
            "key": key_clean,
            "content": content_clean,
            "metadata_json": meta_json,
            "created_at": timestamp,
            "updated_at": timestamp,
        }

        # 2. Write to D1 / SQLite
        try:
            self.db.execute(
                """INSERT OR REPLACE INTO cognitive_memory
                   (id, session_id, memory_type, key, content, metadata_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    mem_id,
                    session_id,
                    m_type,
                    key_clean,
                    content_clean,
                    meta_json,
                    timestamp,
                    timestamp,
                ],
            )
        except Exception as exc:
            logger.debug("Operation error suppressed: %s", exc)

        # 3. Write to disk mirror backup
        self._save_to_disk_mirror(m_type, record)
        return record

    def recall(
        self,
        memory_type: str | MemoryType | None = None,
        key: str | None = None,
        query: str | None = None,
        session_id: str | None = None,
        limit: int = 15,
    ) -> list[dict[str, Any]]:
        """Recalls memories by type, key, substring query, or active session."""
        m_type = (
            memory_type.value
            if isinstance(memory_type, MemoryType)
            else (MemoryType.from_string(memory_type).value if memory_type else None)
        )

        # 1. Try D1 / SQLite query
        try:
            conditions = []
            params: list[Any] = []

            if m_type:
                conditions.append("memory_type = ?")
                params.append(m_type)

            if key:
                conditions.append("key = ?")
                params.append(key.strip())

            if session_id:
                conditions.append("(session_id = ? OR session_id IS NULL)")
                params.append(session_id)

            if query:
                conditions.append("(content LIKE ? OR key LIKE ?)")
                q_param = f"%{query.strip()}%"
                params.extend([q_param, q_param])

            sql = "SELECT * FROM cognitive_memory"
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            sql += " ORDER BY updated_at DESC LIMIT ?"
            params.append(limit)

            rows = self.db.execute(sql, params)
            if rows:
                return rows
        except Exception as exc:
            logger.debug("Operation error suppressed: %s", exc)

        # 2. Fallback to disk mirror
        return self._recall_from_disk_mirror(m_type, key, query, session_id, limit)

    def clear(self, memory_type: str | MemoryType | None = None, session_id: str | None = None) -> int:
        """Clears memories by type and/or session."""
        m_type = (
            memory_type.value
            if isinstance(memory_type, MemoryType)
            else (MemoryType.from_string(memory_type).value if memory_type else None)
        )

        cleared_count = 0
        try:
            conditions = []
            params: list[Any] = []
            if m_type:
                conditions.append("memory_type = ?")
                params.append(m_type)
            if session_id:
                conditions.append("session_id = ?")
                params.append(session_id)

            sql = "DELETE FROM cognitive_memory"
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)

            self.db.execute(sql, params)
            cleared_count += 1
        except Exception as exc:
            logger.debug("Operation error suppressed: %s", exc)

        # Update disk mirror
        types_to_clear = [m_type] if m_type else list(self.VALID_TYPES)
        for t in types_to_clear:
            disk_file = self.storage_dir / f"{t}.json"
            if disk_file.exists():
                try:
                    if session_id:
                        data = json.loads(disk_file.read_text(encoding="utf-8"))
                        filtered = [item for item in data if item.get("session_id") != session_id]
                        disk_file.write_text(json.dumps(filtered, indent=2, ensure_ascii=False), encoding="utf-8")
                    else:
                        disk_file.write_text("[]", encoding="utf-8")
                except Exception as exc:
                    logger.debug("Operation error suppressed: %s", exc)

        return cleared_count

    def _save_to_disk_mirror(self, m_type: str, record: dict[str, Any]) -> None:
        disk_file = self.storage_dir / f"{m_type}.json"
        try:
            items = []
            if disk_file.exists():
                items = json.loads(disk_file.read_text(encoding="utf-8"))
            # Replace existing or append
            items = [item for item in items if item.get("key") != record["key"] or item.get("session_id") != record["session_id"]]
            items.insert(0, record)
            disk_file.write_text(json.dumps(items[:100], indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            logger.debug("Operation error suppressed: %s", exc)

    def _recall_from_disk_mirror(
        self,
        m_type: str | None,
        key: str | None,
        query: str | None,
        session_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        types_to_check = [m_type] if m_type else list(self.VALID_TYPES)
        results: list[dict[str, Any]] = []

        for t in types_to_check:
            disk_file = self.storage_dir / f"{t}.json"
            if not disk_file.exists():
                continue
            try:
                items = json.loads(disk_file.read_text(encoding="utf-8"))
                for item in items:
                    if key and item.get("key") != key:
                        continue
                    if session_id and item.get("session_id") not in (session_id, None):
                        continue
                    if query:
                        q_lower = query.lower()
                        if q_lower not in item.get("content", "").lower() and q_lower not in item.get("key", "").lower():
                            continue
                    results.append(item)
            except Exception as exc:
                logger.debug("Operation error suppressed: %s", exc)

        results.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return results[:limit]

    def get_summary(self) -> dict[str, int]:
        """Returns the number of stored memories per type."""
        summary = {m_type: 0 for m_type in self.VALID_TYPES}
        try:
            rows = self.db.execute("SELECT memory_type, COUNT(*) as c FROM cognitive_memory GROUP BY memory_type")
            for r in rows:
                if r.get("memory_type") in summary:
                    summary[r["memory_type"]] = r.get("c", 0)
        except Exception:
            for m_type in self.VALID_TYPES:
                disk_file = self.storage_dir / f"{m_type}.json"
                if disk_file.exists():
                    try:
                        items = json.loads(disk_file.read_text(encoding="utf-8"))
                        summary[m_type] = len(items)
                    except Exception as exc:
                        logger.debug("Operation error suppressed: %s", exc)
        return summary

    def get_prompt_context(self, session_id: str | None = None, max_per_type: int = 4, include_episodic: bool = False) -> str:
        """Constructs a high-density markdown block of primary cognitive memory.
        
        Per user directive:
        When starting something, it becomes a new chat. Do NOT load previous episodic memories.
        Only load primary memory (semantic project facts/conventions and essential procedural workflows)
        needed across all chats. Working memory is only loaded for the current active session.
        """
        sections = []

        type_headers = {
            "semantic": "📚 PRIMARY MEMORY (Core Project Facts & Conventions)",
            "procedural": "⚙️ PROCEDURAL MEMORY (Workflows & Recipes)",
            "working": "🧠 WORKING MEMORY (Current Session Scratchpad)",
            "episodic": "📜 EPISODIC MEMORY (Current Session Lessons)",
        }

        # Only load primary (semantic) and procedural memory across sessions.
        # Episodic memory from past chats is excluded to ensure every new chat starts clean.
        types_to_load = ["semantic", "procedural"]
        if session_id:
            types_to_load.append("working")
            if include_episodic:
                types_to_load.append("episodic")

        for m_type in types_to_load:
            records = self.recall(
                memory_type=m_type,
                session_id=session_id if m_type in ("working", "episodic") else None,
                limit=max_per_type,
            )
            if not records:
                continue

            lines = [f"#### {type_headers[m_type]}"]
            for r in records:
                key = r.get("key", "note")
                content = r.get("content", "").strip()
                if "\n" in content:
                    lines.append(f"- **{key}**:\n  {content.replace(chr(10), chr(10) + '  ')}")
                else:
                    lines.append(f"- **{key}**: {content}")
            sections.append("\n".join(lines))

        if not sections:
            return ""

        return (
            "### 🏛️ PRIMARY MEMORY (Essential Context):\n"
            + "\n\n".join(sections)
            + "\n\n*Note: Each chat starts clean without previous episodic baggage. Use `read_memory` if specific historical facts or past experiences are explicitly needed.*"
        )


# Global singleton instance
cognitive_memory = CognitiveMemoryStore()
