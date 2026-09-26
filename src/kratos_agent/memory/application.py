"""Application memory for app-specific facts, shortcuts, and quirks."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ApplicationKnowledge:
    application: str
    facts: list[str] = field(default_factory=list)
    shortcuts: dict[str, str] = field(default_factory=dict)
    workflows: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "application": self.application,
            "facts": self.facts,
            "shortcuts": self.shortcuts,
            "workflows": self.workflows,
        }


class ApplicationMemoryStore:
    """Stores application-specific knowledge to speed up automation (§25)."""

    def __init__(self) -> None:
        self._apps: dict[str, ApplicationKnowledge] = {}

    def add_fact(self, application: str, fact: str) -> None:
        app_key = application.strip().lower()
        if app_key not in self._apps:
            self._apps[app_key] = ApplicationKnowledge(application=application)
        if fact not in self._apps[app_key].facts:
            self._apps[app_key].facts.append(fact)

    def add_shortcut(self, application: str, action: str, hotkey: str) -> None:
        app_key = application.strip().lower()
        if app_key not in self._apps:
            self._apps[app_key] = ApplicationKnowledge(application=application)
        self._apps[app_key].shortcuts[action] = hotkey

    def get_knowledge(self, application: str) -> ApplicationKnowledge | None:
        return self._apps.get(application.strip().lower())
