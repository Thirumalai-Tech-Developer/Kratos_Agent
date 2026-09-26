"""
Input Interlock Subsystem.
Monitors physical user input. If a human moves the mouse or types,
the agent must yield (pause its own input) to avoid fighting the user.
"""
import time


class InputInterlock:
    def __init__(self):
        self._last_human_input = 0.0
        
    def record_human_activity(self):
        self._last_human_input = time.time()
        
    def is_locked(self) -> bool:
        """Returns True if a human has interacted recently."""
        return (time.time() - self._last_human_input) < 1.0

interlock = InputInterlock()
