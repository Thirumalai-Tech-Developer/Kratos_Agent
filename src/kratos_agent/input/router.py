from __future__ import annotations

from typing import Any

from .envelope import InputEnvelope


class UnifiedInputRouter:
    """Normalizes every interface into the same request envelope.

    It deliberately performs no semantic classification. Meaning belongs to Gemini.
    """

    def build(
        self,
        text: str = "",
        *,
        source: str = "unknown",
        session_id: str | None = None,
        **context: Any,
    ) -> InputEnvelope:
        return InputEnvelope(
            text=text or "",
            source=source,
            session_id=session_id,
            **context,
        )


_global_router: UnifiedInputRouter | None = None


def get_input_router() -> UnifiedInputRouter:
    global _global_router
    if _global_router is None:
        _global_router = UnifiedInputRouter()
    return _global_router
