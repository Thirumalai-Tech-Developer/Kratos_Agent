"""Memory Plugin - Integrates 4-tier cognitive memory into DeepSeek Harness."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..plugin import HarnessPlugin, PluginMetadata

if TYPE_CHECKING:
    from kratos_agent.core.cognitive_memory import CognitiveMemoryStore

    from ..kernel import HarnessKernel

logger = logging.getLogger(__name__)


class MemoryPlugin(HarnessPlugin):
    """Provides cognitive memory capabilities across working, episodic, semantic, and procedural stores."""

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(
            metadata=PluginMetadata(
                name="memory",
                version="1.0.0",
                description="Cognitive multi-tier memory subsystem for DeepSeek Harness.",
                category="memory",
                required_services=[],
                provides_services=["memory"],
            ),
            config=config,
        )
        self._local_cognitive_store: CognitiveMemoryStore | None = None

    def on_register(self) -> None:
        """Called when memory plugin is registered."""
        pass

    def on_start(self) -> None:
        """Called when memory plugin starts."""
        pass

    def on_stop(self) -> None:
        """Called when memory plugin stops."""
        pass

    def on_error(self, exc: Exception) -> None:
        """Called when an error occurs in the memory plugin."""
        super().on_error(exc)

    def on_load(self, kernel: HarnessKernel) -> None:
        super().on_load(kernel)
        kernel.register_service("memory", self)

    def on_unload(self) -> None:
        if self.kernel:
            self.kernel.unregister_service("memory")
        super().on_unload()

    def _get_store(self) -> CognitiveMemoryStore | None:
        """Obtain CognitiveMemoryStore from runtime or local fallback."""
        if self.kernel and self.kernel.runtime:
            runtime_mem = getattr(self.kernel.runtime, "memory", None)
            if runtime_mem and hasattr(runtime_mem, "cognitive_store"):
                return runtime_mem.cognitive_store
            cog_store = getattr(self.kernel.runtime, "cognitive_store", None)
            if cog_store:
                return cog_store

        if self._local_cognitive_store is None:
            try:
                from kratos_agent.core.cognitive_memory import CognitiveMemoryStore

                self._local_cognitive_store = CognitiveMemoryStore()
            except Exception as e:
                logger.warning(f"[MemoryPlugin] Could not initialize fallback CognitiveMemoryStore: {e}")
        return self._local_cognitive_store

    def save(
        self,
        tier: str,
        content: str,
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> str | None:
        """Save a memory record into the designated cognitive tier."""
        store = self._get_store()
        if not store:
            return None
        record = store.save(
            tier=tier,
            content=content,
            importance=importance,
            metadata=metadata,
            tags=tags,
        )
        if self.kernel:
            self.kernel.emit("memory_saved", tier=tier, memory_id=record.id)
        return record.id

    def read(
        self,
        tier: str | None = None,
        limit: int = 10,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve memories filtered by tier and optional keyword search."""
        store = self._get_store()
        if not store:
            return []
        records = store.search(tier=tier, query=query, limit=limit)
        return [r.to_dict() for r in records]

    def clear(self, tier: str | None = None) -> int:
        """Clear memories in a tier or all tiers."""
        store = self._get_store()
        if not store:
            return 0
        cleared = store.clear(tier=tier)
        if self.kernel:
            self.kernel.emit("memory_cleared", tier=tier, count=cleared)
        return cleared

    def build_context_block(self, limit: int = 5) -> str:
        """Render a formatted markdown block of active memories for prompt injection."""
        store = self._get_store()
        if not store:
            return ""
        working = store.get_active_working_context(limit=limit)
        semantic = store.search(tier="semantic", limit=3)
        procedural = store.search(tier="procedural", limit=3)

        parts = []
        if working:
            parts.append("### Active Working Memory\n" + "\n".join(f"- {r.content}" for r in working))
        if semantic:
            parts.append("### Relevant Semantic Knowledge\n" + "\n".join(f"- {r.content}" for r in semantic))
        if procedural:
            parts.append("### Established Procedures\n" + "\n".join(f"- {r.content}" for r in procedural))

        return "\n\n".join(parts)
