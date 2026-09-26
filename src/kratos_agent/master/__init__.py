"""Master layer for Kratos Agent (Gemini Live perception, supervision, voice)."""
from .prompts import KRATOS_MASTER_SYSTEM_PROMPT
from .protocol import (
    CommandAction,
    CommandBus,
    CommandPriority,
    MasterCommand,
    SlaveAck,
    SlaveResult,
    get_command_bus,
)
from .supervisor import MasterSupervisor, get_master_supervisor

__all__ = [
    "KRATOS_MASTER_SYSTEM_PROMPT",
    "CommandAction",
    "CommandBus",
    "CommandPriority",
    "MasterCommand",
    "MasterSupervisor",
    "SlaveAck",
    "SlaveResult",
    "get_command_bus",
    "get_master_supervisor",
]
