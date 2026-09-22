"""Thread-safe event bus for decoupled agent event dispatch."""
from __future__ import annotations
import threading
from typing import Callable, Dict, List, Optional, Set

from kratos_agent.events.models import AgentEvent, EventType


class EventBus:
    """Publishes structured AgentEvents to registered subscribers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: Dict[EventType, List[Callable[[AgentEvent], None]]] = {}
        self._global_subscribers: List[Callable[[AgentEvent], None]] = []

    def subscribe(self, event_type: EventType, handler: Callable[[AgentEvent], None]) -> None:
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            if handler not in self._subscribers[event_type]:
                self._subscribers[event_type].append(handler)

    def subscribe_all(self, handler: Callable[[AgentEvent], None]) -> None:
        with self._lock:
            if handler not in self._global_subscribers:
                self._global_subscribers.append(handler)

    def unsubscribe(self, handler: Callable[[AgentEvent], None]) -> None:
        with self._lock:
            for handlers in self._subscribers.values():
                if handler in handlers:
                    handlers.remove(handler)
            if handler in self._global_subscribers:
                self._global_subscribers.remove(handler)

    def emit(self, event: AgentEvent) -> None:
        with self._lock:
            handlers = list(self._subscribers.get(event.type, []))
            global_handlers = list(self._global_subscribers)

        for handler in handlers + global_handlers:
            try:
                handler(event)
            except Exception:
                pass


_agent_event_bus: Optional[EventBus] = None


def get_agent_event_bus() -> EventBus:
    global _agent_event_bus
    if _agent_event_bus is None:
        _agent_event_bus = EventBus()
    return _agent_event_bus
