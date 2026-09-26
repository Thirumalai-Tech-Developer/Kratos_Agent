"""Headroom Context Compression Plugin for Kratos Agent.

Integrates the Headroom library (headroomlabs-ai/headroom) for automatic
context compression before LLM calls. Reduces token usage by 20-60% on
tool outputs, logs, JSON, and conversation history while preserving accuracy.

Headroom is optional — if not installed, Kratos operates normally.
When installed, compression auto-enables and reports savings via the event bus.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..plugin import HarnessPlugin, PluginMetadata

if TYPE_CHECKING:
    from ..kernel import HarnessKernel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy import guard — headroom is optional
# ---------------------------------------------------------------------------
_headroom_available: bool | None = None


def is_headroom_available() -> bool:
    """Check if headroom-ai is installed. Cached after first call."""
    global _headroom_available
    if _headroom_available is None:
        try:
            import headroom  # noqa: F401
            _headroom_available = True
        except ImportError:
            _headroom_available = False
    return _headroom_available


@dataclass
class HeadroomStats:
    """Tracks cumulative compression statistics across the session."""
    total_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens_saved: int = 0
    per_content_type: dict[str, int] = field(default_factory=dict)
    last_ratio: float = 0.0
    enabled: bool = True

    @property
    def overall_ratio(self) -> float:
        if self.total_input_tokens == 0:
            return 0.0
        return 1.0 - (self.total_output_tokens / self.total_input_tokens)

    @property
    def savings_percent(self) -> float:
        return round(self.overall_ratio * 100, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_calls": self.total_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens_saved": self.total_tokens_saved,
            "savings_percent": self.savings_percent,
            "per_content_type": dict(self.per_content_type),
            "enabled": self.enabled,
        }


class HeadroomPlugin(HarnessPlugin):
    """Headroom context compression — 20-60% token savings on tool outputs, logs, and history.

    Lifecycle:
        UNLOADED → on_load() → LOADED → on_enable() detects headroom → ENABLED (or ERROR)

    Services registered:
        - "headroom" → this plugin instance (used by context_pipeline, compactor)

    Events emitted via kernel:
        - "headroom:compressed" → {tokens_saved, ratio, content_type}
    """

    metadata = PluginMetadata(
        name="headroom",
        version="1.0.0",
        description="Headroom context compression — 20-60% token savings",
        author="Kratos Agent",
        category="general",
        tags=["compression", "tokens", "optimization"],
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config=config)
        self.stats = HeadroomStats()
        self._compress_fn = None
        self._model_name: str = "gpt-4o"  # Default tokenizer model for Headroom

    def on_load(self, kernel: HarnessKernel) -> None:
        """Attach to kernel context."""
        super().on_load(kernel)

    def on_enable(self) -> None:
        """Initialize Headroom if available and register service."""
        super().on_enable()

        if not is_headroom_available():
            logger.info("[HeadroomPlugin] headroom-ai not installed — compression disabled.")
            return

        try:
            from headroom import compress
            self._compress_fn = compress
            logger.info("[HeadroomPlugin] Headroom compression engine loaded.")

            # Register ourselves as a shared service on the kernel
            if self.kernel:
                self.kernel.register_service("headroom", self)
        except Exception as e:
            logger.warning(f"[HeadroomPlugin] Failed to initialize Headroom: {e}")
            self._compress_fn = None
            self.error_message = str(e)

    def on_disable(self) -> None:
        """Cleanup service registration."""
        if self.kernel:
            self.kernel.unregister_service("headroom")
        self._compress_fn = None
        super().on_disable()

    @property
    def available(self) -> bool:
        """True if Headroom is installed and initialized."""
        return self._compress_fn is not None and self.stats.enabled

    def set_model(self, model_name: str) -> None:
        """Update the tokenizer model used by Headroom for token counting."""
        self._model_name = model_name

    def toggle(self, enabled: bool) -> None:
        """Enable/disable compression at runtime."""
        self.stats.enabled = enabled
        logger.info(f"[HeadroomPlugin] Compression {'enabled' if enabled else 'disabled'}.")

    def compress_messages(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Compress a list of chat messages using Headroom.

        Args:
            messages: OpenAI-format message list [{role, content}, ...]
            model: Model name for tokenizer (defaults to self._model_name)

        Returns:
            (compressed_messages, stats_dict)
        """
        if not self.available or not messages:
            return messages, {"compressed": False, "reason": "headroom_unavailable" if not self.available else "empty_messages"}

        target_model = model or self._model_name
        t0 = time.monotonic()

        try:
            result = self._compress_fn(messages, model=target_model)

            tokens_saved = getattr(result, "tokens_saved", 0)
            ratio = getattr(result, "compression_ratio", 0.0)
            compressed_msgs = getattr(result, "messages", messages)

            # Update cumulative stats
            input_tokens = getattr(result, "original_tokens", 0)
            output_tokens = input_tokens - tokens_saved if input_tokens else 0

            self.stats.total_calls += 1
            self.stats.total_input_tokens += input_tokens
            self.stats.total_output_tokens += output_tokens
            self.stats.total_tokens_saved += tokens_saved
            self.stats.last_ratio = ratio

            elapsed_ms = (time.monotonic() - t0) * 1000

            stats = {
                "compressed": True,
                "tokens_saved": tokens_saved,
                "compression_ratio": ratio,
                "elapsed_ms": round(elapsed_ms, 2),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }

            # Emit event if kernel is available
            if self.kernel:
                try:
                    self.kernel.emit("headroom:compressed", stats)
                except Exception as exc:
                    logger.debug("Operation error suppressed: %s", exc)  # Don't let event bus errors break compression

            return compressed_msgs, stats

        except Exception as e:
            logger.warning(f"[HeadroomPlugin] Compression failed, passing through: {e}")
            return messages, {"compressed": False, "reason": str(e)}

    def compress_text(self, text: str, content_type: str = "text") -> tuple[str, dict[str, Any]]:
        """Compress a single text string (tool output, log, etc).

        Wraps text in a message, compresses, and extracts the result.
        Tracks per-content-type savings.

        Args:
            text: Raw text to compress
            content_type: Label for stats tracking (e.g., "json", "log", "code")

        Returns:
            (compressed_text, stats_dict)
        """
        if not self.available or not text or len(text) < 200:
            return text, {"compressed": False, "reason": "too_short" if text and len(text) < 200 else "headroom_unavailable"}

        msgs = [{"role": "user", "content": text}]
        compressed_msgs, stats = self.compress_messages(msgs)

        if stats.get("compressed"):
            compressed_text = compressed_msgs[0].get("content", text) if compressed_msgs else text
            # Track per content type
            saved = stats.get("tokens_saved", 0)
            self.stats.per_content_type[content_type] = self.stats.per_content_type.get(content_type, 0) + saved
            return compressed_text, stats

        return text, stats

    def get_status(self) -> dict[str, Any]:
        """Return runtime status including compression stats."""
        base = super().get_status()
        base["headroom_installed"] = is_headroom_available()
        base["compression_enabled"] = self.available
        base["stats"] = self.stats.to_dict()
        return base

    def get_stats_display(self) -> str:
        """Format stats for CLI display."""
        if not is_headroom_available():
            return "⚙️  Headroom: not installed (pip install headroom-ai)"

        if not self.stats.enabled:
            return "⚙️  Headroom: disabled (use /headroom on to enable)"

        if self.stats.total_calls == 0:
            return "⚙️  Headroom: enabled, no compressions yet this session"

        lines = [
            "⚙️  Headroom Context Compression Stats",
            f"   Status:        {'✅ enabled' if self.stats.enabled else '❌ disabled'}",
            f"   Total calls:   {self.stats.total_calls}",
            f"   Tokens saved:  {self.stats.total_tokens_saved:,}",
            f"   Savings:       {self.stats.savings_percent}%",
            f"   Last ratio:    {self.stats.last_ratio:.1%}",
        ]
        if self.stats.per_content_type:
            lines.append("   By content type:")
            for ct, saved in sorted(self.stats.per_content_type.items(), key=lambda x: -x[1]):
                lines.append(f"     {ct}: {saved:,} tokens saved")
        return "\n".join(lines)
