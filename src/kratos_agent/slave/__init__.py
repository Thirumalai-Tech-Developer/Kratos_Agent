"""Slave execution layer for Kratos Agent (OmniRoute / Brain runtime)."""
from .executor import SlaveExecutor, get_slave_executor
from .prompts import KRATOS_SLAVE_SYSTEM_PROMPT

__all__ = [
    "SlaveExecutor",
    "get_slave_executor",
    "KRATOS_SLAVE_SYSTEM_PROMPT",
]
