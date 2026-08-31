"""Composable, inspectable instruction assembly for model requests."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List


@dataclass(frozen=True)
class InstructionModule:
    name: str
    layer: str  # system | developer | persona | project | runtime
    render: Callable[[], str]
    priority: int = 100


class InstructionEngine:
    """Orders instruction layers; it never hides them in a hard-coded prompt."""
    def __init__(self) -> None:
        self._modules: Dict[str, InstructionModule] = {}

    def register(self, module: InstructionModule) -> None:
        self._modules[module.name] = module

    def unregister(self, name: str) -> None:
        self._modules.pop(name, None)

    def build(self, active: Iterable[str] | None = None) -> List[Dict[str, str]]:
        selected = self._modules.values() if active is None else (
            self._modules[name] for name in active if name in self._modules
        )
        sections = []
        for module in sorted(selected, key=lambda item: (item.priority, item.name)):
            content = module.render().strip()
            if content:
                sections.append({"name": module.name, "layer": module.layer, "content": content})
        return sections

    @staticmethod
    def as_system_text(sections: List[Dict[str, str]]) -> str:
        return "\n\n".join(
            f"## {section['layer'].upper()}: {section['name']}\n{section['content']}"
            for section in sections
        )
