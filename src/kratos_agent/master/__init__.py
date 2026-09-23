"""Master layer for Kratos Agent (Gemini Live perception, supervision, voice)."""
from .protocol import (
    CommandAction,
    CommandPriority,
    MasterCommand,
    SlaveAck,
    SlaveResult,
    CommandBus,
    get_command_bus,
)
from .supervisor import MasterSupervisor, get_master_supervisor
from .prompts import KRATOS_MASTER_SYSTEM_PROMPT

__all__ = [
    "CommandAction",
    "CommandPriority",
    "MasterCommand",
    "SlaveAck",
    "SlaveResult",
    "CommandBus",
    "get_command_bus",
    "MasterSupervisor",
    "get_master_supervisor",
    "KRATOS_MASTER_SYSTEM_PROMPT",
]
