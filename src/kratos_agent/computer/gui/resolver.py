"""Semantic element resolver with confidence scoring and ambiguity detection."""
from __future__ import annotations
import time
from typing import Any, Dict, List, Optional, Tuple

from kratos_agent.computer.gui.models import GUIElement, StaleElementTracker
from kratos_agent.computer.gui.selectors import ElementSelector
from kratos_agent.computer.gui.errors import AmbiguousTargetError, TargetNotFoundError, StaleElementError
from kratos_agent.computer.gui.backends.base import GUIBackend
from kratos_agent.computer.gui.backends.windows_uia import WindowsUIABackend
from kratos_agent.computer.gui.backends.playwright import PlaywrightBackend


class SemanticResolver:
    """Resolves semantic target specifications to concrete, verified UI elements.
    
    Priority ladder:
    1. Native application API
    2. Accessibility API (UIA/AT-SPI)
    3. Browser DOM (Playwright/CDP)
    4. Semantic UI element
    5. Keyboard navigation
    6. Application-specific adapter
    7. Vision for observation only. Vision never supplies input coordinates.
    """

    def __init__(self) -> None:
        self.stale_tracker = StaleElementTracker()
        self._backends: List[GUIBackend] = []
        self._init_backends()

    def _init_backends(self) -> None:
        # Register available backends sorted by priority
        backends: List[GUIBackend] = [
            PlaywrightBackend(),
            WindowsUIABackend(),
        ]
        self._backends = sorted([b for b in backends if b.is_available()], key=lambda x: x.priority)

    def resolve(
        self,
        target: Dict[str, Any],
        elements: Optional[List[GUIElement]] = None,
        allow_ambiguous: bool = False,
    ) -> GUIElement:
        """Resolves target dictionary (name, role, id, selector) to a single high-confidence GUIElement."""
        name = target.get("name")
        role = target.get("role")
        elem_id = target.get("id") or target.get("ref")
        selector = ElementSelector(name=name, role=role, element_id=elem_id)

        # 1. If candidate list not provided, gather from available backends in priority order
        candidates: List[Tuple[GUIElement, float]] = []

        if elements is not None:
            for el in elements:
                # Check stale element
                if self.stale_tracker.is_stale(el):
                    continue
                matched, score = selector.matches(el)
                if matched:
                    candidates.append((el, score * el.confidence))
        else:
            # Query backends by priority ladder
            for backend in self._backends:
                backend_elements = backend.dump_tree(max_nodes=300)
                for el in backend_elements:
                    matched, score = selector.matches(el)
                    if matched:
                        # Weight score by backend priority
                        priority_weight = max(0.6, 1.0 - (backend.priority * 0.05))
                        final_conf = score * priority_weight
                        candidates.append((el, final_conf))

                if candidates:
                    # Found matches in a higher-priority backend; do not fall back to lower backends
                    break

        if not candidates:
            raise TargetNotFoundError(f"Target '{target}' could not be resolved in the current UI environment.")

        # Sort candidates by descending confidence
        candidates.sort(key=lambda x: x[1], reverse=True)
        best_elem, best_score = candidates[0]

        # 2. Check for Ambiguity
        if len(candidates) > 1 and not allow_ambiguous:
            second_elem, second_score = candidates[1]
            # If top two candidates are both high confidence and very close in score
            if best_score > 0.80 and (best_score - second_score) < 0.05:
                raise AmbiguousTargetError(
                    f"Ambiguous target: multiple UI elements matched '{target}' with similar confidence "
                    f"({round(best_score, 2)} vs {round(second_score, 2)}). "
                    f"Candidate 1: '{best_elem.name}' ({best_elem.role}), "
                    f"Candidate 2: '{second_elem.name}' ({second_elem.role}). "
                    f"Please specify additional attributes (e.g. role, parent window, or index)."
                )

        best_elem.confidence = best_score
        return best_elem


_resolver: Optional[SemanticResolver] = None


def get_resolver() -> SemanticResolver:
    global _resolver
    if _resolver is None:
        _resolver = SemanticResolver()
    return _resolver
