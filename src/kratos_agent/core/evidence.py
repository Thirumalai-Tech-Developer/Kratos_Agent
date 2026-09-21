from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any, Literal

EvidenceMethod = Literal[
    "cdp_js", "a11y", "ocr", "screen_diff", "fs_stat", "process",
    "registry", "http", "window", "audio_level", "pixel_sample", "command_exit",
]

@dataclass(slots=True)
class Evidence:
    """Proof that an outcome is true. Never constructed by hand from an
    action's return value — always from a perception read taken AFTER the action."""
    claim:        str                      # human-readable assertion, e.g. "video is playing"
    method:       EvidenceMethod
    met:          bool                     # ← THE ONLY FIELD THAT DECIDES COMPLETION
    observed:     dict[str, Any]           # raw values actually read
    confidence:   float = 1.0              # 0..1; < 0.6 requires a second method
    samples:      int = 1                  # >1 for time-based assertions (playback advancing)
    interval_ms:  int = 0                  # spacing between samples
    frame_ref:    str | None = None        # screenshot backing this, if visual
    detail:       str = ""                 # spoken-safe, ≤ 160 chars, no JSON
    sampled_at:   str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    stale_ms:     int = 0                  # age of the observation at gate time

    @property
    def trustworthy(self) -> bool:
        return self.met and self.confidence >= 0.6 and self.stale_ms < 5000

    def to_model_dict(self) -> dict:
        """Compact form for the model context."""
        return {
            "claim": self.claim,
            "met": self.met,
            "method": self.method,
            "confidence": round(self.confidence, 2),
            "samples": self.samples,
            "detail": self.detail,
            "observed": self.observed,
            "frame_ref": self.frame_ref,
        }


@dataclass(slots=True)
class OutcomeAssertion:
    """Declarative post-condition. Written by the PLANNER when the step is created,
    not by the executor after the fact — otherwise the executor grades its own homework."""
    kind:   str
    params: dict[str, Any] = field(default_factory=dict)
    timeout_s: float = 10.0
    poll_ms:   int = 250
    require_samples: int = 1     # 2 for anything time-based
    sample_gap_ms:   int = 1500
