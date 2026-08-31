"""Decoupled thread-safe event bus for the Kratos agent runtime.

Allows agent components (planner, task manager, workspace tracker, verification manager)
and presentation layers (TUI Live Renderer, CLI, logger) to emit and subscribe to
structured RuntimeEvents.
"""
from __future__ import annotations

import threading
from typing import Callable, Dict, List, Optional
from .runtime_contracts import EventKind, RuntimeEvent


EventListener = Callable[[RuntimeEvent], None]


class EventBus:
    """Thread-safe publish/subscribe bus for RuntimeEvents."""

    def __init__(self) -> None:
        self._listeners: List[EventListener] = []
        self._kind_listeners: Dict[EventKind, List[EventListener]] = {}
        self._lock = threading.RLock()

    def subscribe(self, listener: EventListener, event_kind: Optional[EventKind] = None) -> None:
        """Subscribe a listener to all events or a specific EventKind."""
        with self._lock:
            if event_kind is None:
                if listener not in self._listeners:
                    self._listeners.append(listener)
            else:
                if event_kind not in self._kind_listeners:
                    self._kind_listeners[event_kind] = []
                if listener not in self._kind_listeners[event_kind]:
                    self._kind_listeners[event_kind].append(listener)

    def unsubscribe(self, listener: EventListener, event_kind: Optional[EventKind] = None) -> None:
        """Unsubscribe a listener."""
        with self._lock:
            if event_kind is None:
                if listener in self._listeners:
                    self._listeners.remove(listener)
                for listeners in self._kind_listeners.values():
                    if listener in listeners:
                        listeners.remove(listener)
            else:
                if event_kind in self._kind_listeners and listener in self._kind_listeners[event_kind]:
                    self._kind_listeners[event_kind].remove(listener)

    def publish(self, event: RuntimeEvent) -> None:
        """Publish a RuntimeEvent to all matching subscribers."""
        with self._lock:
            # Snapshot lists to avoid issues if a listener modifies subscriptions during dispatch
            all_listeners = list(self._listeners)
            kind_listeners = list(self._kind_listeners.get(event.kind, []))

        for listener in all_listeners:
            try:
                listener(event)
            except Exception:
                pass

        for listener in kind_listeners:
            try:
                listener(event)
            except Exception:
                pass

    def clear(self) -> None:
        """Clear all listeners."""
        with self._lock:
            self._listeners.clear()
            self._kind_listeners.clear()


# Global default event bus
event_bus = EventBus()
