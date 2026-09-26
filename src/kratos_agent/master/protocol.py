"""Master-Slave structured communication protocol for Kratos Agent.

Enforces strict separation of responsibilities:
- Master (Gemini Live): Perception, conversational interface, intent interpretation, high-level supervision.
- Slave (OmniRoute / Brain Runtime): Tool selection, execution, computer control, verification, recovery.
"""
from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

import asyncio
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CommandPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    CANCEL = "cancel"

    @classmethod
    def from_str(cls, val: str) -> CommandPriority:
        try:
            return cls(val.lower())
        except Exception:
            return cls.NORMAL


class CommandAction(str, Enum):
    OBSERVE = "observe"
    SEARCH = "search"
    NAVIGATE = "navigate"
    OPEN_APPLICATION = "open_application"
    BROWSER_ACTION = "browser_action"
    GUI_ACTION = "gui_action"
    FILE_ACTION = "file_action"
    SYSTEM_ACTION = "system_action"
    TERMINAL_ACTION = "terminal_action"
    DOWNLOAD = "download"
    INSTALL = "install"
    VERIFY = "verify"
    RECOVER = "recover"
    CANCEL = "cancel"
    PAUSE = "pause"
    RESUME = "resume"
    CONTINUE = "continue"
    ASK_USER = "ask_user"
    GENERIC_TASK = "generic_task"

    @classmethod
    def from_str(cls, val: str) -> CommandAction:
        clean = val.lower().replace(".", "_")
        for member in cls:
            if member.value == clean or member.name.lower() == clean:
                return member
        return cls.GENERIC_TASK


@dataclass
class MasterCommand:
    """Structured actionable command from Gemini Live Master to OmniRoute Slave."""
    command_id: str
    session_id: str
    task_id: str
    objective: str
    action: str
    request_id: str = ""
    turn_id: str = ""
    action_id: str = ""
    tool_call_id: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    expected_result: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    priority: str = CommandPriority.NORMAL.value
    timeout: float = 60.0
    created_at: float = field(default_factory=time.time)

    @classmethod
    def create(
        cls,
        objective: str,
        action: str,
        parameters: dict[str, Any] | None = None,
        constraints: dict[str, Any] | None = None,
        expected_result: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        priority: str = "normal",
        timeout: float = 60.0,
        session_id: str | None = None,
        task_id: str | None = None,
        request_id: str | None = None,
        turn_id: str | None = None,
        action_id: str | None = None,
        tool_call_id: str | None = None,
    ) -> MasterCommand:
        cid = f"CMD-{uuid.uuid4().hex[:8].upper()}"
        tid = task_id or f"TASK-{uuid.uuid4().hex[:8].upper()}"
        sid = session_id or f"LIVE-{uuid.uuid4().hex[:6].upper()}"
        return cls(
            command_id=cid,
            session_id=sid,
            task_id=tid,
            request_id=request_id or "",
            turn_id=turn_id or "",
            action_id=action_id or f"ACT-{uuid.uuid4().hex[:8].upper()}",
            tool_call_id=tool_call_id or "",
            objective=objective,
            action=action,
            parameters=parameters or {},
            constraints=constraints or {},
            expected_result=expected_result or {},
            context=context or {},
            priority=priority,
            timeout=timeout,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "request_id": self.request_id,
            "turn_id": self.turn_id,
            "action_id": self.action_id,
            "tool_call_id": self.tool_call_id,
            "objective": self.objective,
            "action": self.action,
            "parameters": self.parameters,
            "constraints": self.constraints,
            "expected_result": self.expected_result,
            "context": self.context,
            "priority": self.priority,
            "timeout": self.timeout,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MasterCommand:
        return cls(
            command_id=data["command_id"],
            session_id=data.get("session_id", "default"),
            task_id=data["task_id"],
            request_id=data.get("request_id", ""),
            turn_id=data.get("turn_id", ""),
            action_id=data.get("action_id", ""),
            tool_call_id=data.get("tool_call_id", ""),
            objective=data.get("objective", ""),
            action=data.get("action", "generic_task"),
            parameters=data.get("parameters", {}),
            constraints=data.get("constraints", {}),
            expected_result=data.get("expected_result", {}),
            context=data.get("context", {}),
            priority=data.get("priority", "normal"),
            timeout=float(data.get("timeout", 60.0)),
            created_at=float(data.get("created_at", time.time())),
        )


@dataclass
class SlaveAck:
    """Immediate acknowledgement returned by Slave to Master."""
    command_id: str
    task_id: str
    accepted: bool
    status: str = "accepted"  # accepted, rejected, busy, blocked, failed
    type: str = "ACK"
    message: str | None = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "command_id": self.command_id,
            "task_id": self.task_id,
            "accepted": self.accepted,
            "status": self.status,
            "message": self.message,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SlaveAck:
        return cls(
            command_id=data["command_id"],
            task_id=data["task_id"],
            accepted=bool(data.get("accepted", True)),
            status=data.get("status", "accepted"),
            type=data.get("type", "ACK"),
            message=data.get("message"),
            created_at=float(data.get("created_at", time.time())),
        )


@dataclass
class SlaveResult:
    """Deterministic result and evidence returned by Slave to Master after execution."""
    command_id: str
    task_id: str
    status: str  # success, failed, partial, waiting, permission_required, ambiguous
    verified: bool
    type: str = "RESULT"
    terminal: bool = True
    state: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    recovery_attempts: int = 0
    duration_ms: float = 0.0
    created_at: float = field(default_factory=time.time)

    def is_success(self) -> bool:
        return self.status == "success" and self.verified

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "command_id": self.command_id,
            "task_id": self.task_id,
            "status": self.status,
            "verified": self.verified,
            "terminal": self.terminal,
            "state": self.state,
            "evidence": self.evidence,
            "error": self.error,
            "recovery_attempts": self.recovery_attempts,
            "duration_ms": self.duration_ms,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SlaveResult:
        return cls(
            command_id=data["command_id"],
            task_id=data["task_id"],
            status=data.get("status", "failed"),
            verified=bool(data.get("verified", False)),
            type=data.get("type", "RESULT"),
            terminal=bool(data.get("terminal", True)),
            state=data.get("state"),
            evidence=data.get("evidence", {}),
            error=data.get("error"),
            recovery_attempts=int(data.get("recovery_attempts", 0)),
            duration_ms=float(data.get("duration_ms", 0.0)),
            created_at=float(data.get("created_at", time.time())),
        )


class CommandBus:
    """Asynchronous, thread-safe message bus correlating MasterCommands, SlaveAcks, and SlaveResults."""

    def __init__(self) -> None:
        self._commands: asyncio.PriorityQueue[tuple[int, float, MasterCommand]] | None = None
        self._results: dict[str, asyncio.Future[SlaveResult]] = {}
        self._acks: dict[str, asyncio.Future[SlaveAck]] = {}
        self._active_tasks: dict[str, MasterCommand] = {}
        self._listeners: list[Callable[[dict[str, Any]], None]] = []
        self._lock: asyncio.Lock | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _ensure_queue(self) -> tuple[asyncio.PriorityQueue[tuple[int, float, MasterCommand]], asyncio.Lock]:
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if self._commands is None or self._loop != current_loop:
            self._loop = current_loop
            self._commands = asyncio.PriorityQueue()
            self._lock = asyncio.Lock()
        return self._commands, self._lock

    def add_listener(self, callback: Callable[[dict[str, Any]], None]) -> None:
        self._listeners.append(callback)

    def _notify(self, event: dict[str, Any]) -> None:
        for listener in self._listeners:
            try:
                listener(event)
            except Exception as exc:
                logger.debug("Operation error suppressed: %s", exc)

    def _priority_score(self, priority: str) -> int:
        mapping = {
            CommandPriority.CANCEL.value: 0,
            CommandPriority.URGENT.value: 1,
            CommandPriority.HIGH.value: 2,
            CommandPriority.NORMAL.value: 3,
            CommandPriority.LOW.value: 4,
        }
        return mapping.get(priority.lower(), 3)

    async def send_command(self, command: MasterCommand) -> tuple[asyncio.Future[SlaveAck], asyncio.Future[SlaveResult]]:
        """Registers and enqueues a command from the Master, returning futures for Ack and Result."""
        queue, lock = self._ensure_queue()
        loop = asyncio.get_running_loop()
        ack_future: asyncio.Future[SlaveAck] = loop.create_future()
        result_future: asyncio.Future[SlaveResult] = loop.create_future()

        async with lock:
            self._acks[command.command_id] = ack_future
            self._results[command.command_id] = result_future
            self._active_tasks[command.task_id] = command
            score = self._priority_score(command.priority)
            await queue.put((score, command.created_at, command))

        self._notify({"type": "COMMAND_SENT", "command": command.to_dict()})
        return ack_future, result_future

    async def get_next_command(self) -> MasterCommand:
        """Called by the Slave executor to dequeue the highest-priority command."""
        queue, _ = self._ensure_queue()
        _, _, command = await queue.get()
        return command

    async def publish_ack(self, ack: SlaveAck) -> None:
        """Called by the Slave to acknowledge receipt of a command."""
        _, lock = self._ensure_queue()
        async with lock:
            fut = self._acks.get(ack.command_id)
            if fut and not fut.done():
                fut.set_result(ack)

        self._notify({"type": "ACK_RECEIVED", "ack": ack.to_dict()})

    async def publish_result(self, result: SlaveResult) -> None:
        """Called by the Slave to return deterministic execution evidence."""
        _, lock = self._ensure_queue()
        async with lock:
            fut = self._results.get(result.command_id)
            if fut and not fut.done():
                fut.set_result(result)
            self._active_tasks.pop(result.task_id, None)

        self._notify({"type": "RESULT_RECEIVED", "result": result.to_dict()})


    async def cancel_task(self, task_id: str, reason: str = "User cancelled") -> bool:
        """Cancels an active task across the bus."""
        _, lock = self._ensure_queue()
        async with lock:
            command = self._active_tasks.get(task_id)
            if not command:
                return False

        cancel_cmd = MasterCommand.create(
            objective=f"Cancel task {task_id}",
            action=CommandAction.CANCEL.value,
            parameters={"target_task_id": task_id, "reason": reason},
            priority=CommandPriority.CANCEL.value,
            task_id=task_id,
            session_id=command.session_id,
        )
        await self.send_command(cancel_cmd)
        return True

    def get_active_task(self, task_id: str) -> MasterCommand | None:
        return self._active_tasks.get(task_id)

    def list_active_tasks(self) -> list[MasterCommand]:
        return list(self._active_tasks.values())


# Global singleton command bus
_global_command_bus: CommandBus | None = None


def get_command_bus() -> CommandBus:
    global _global_command_bus
    if _global_command_bus is None:
        _global_command_bus = CommandBus()
    return _global_command_bus
