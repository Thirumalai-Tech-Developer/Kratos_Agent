"""Kratos application composition root with an explicit agent pipeline."""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

from kratos_agent.brain import BrainChatModel, get_default_model
from kratos_agent.core.agent_loop import AgentLoop
from kratos_agent.core.approval_mode import ApprovalMode, approval_gate
from kratos_agent.core.context_pipeline import ContextBuilder, ContextBudget
from kratos_agent.core.event_store import EventStore
from kratos_agent.core.instruction_engine import InstructionEngine, InstructionModule
from kratos_agent.core.memory import memory
from kratos_agent.core.mcp_runtime import McpManager
from kratos_agent.core.provider_runtime import BrainAdapter
from kratos_agent.core.runtime_contracts import ChatMessage, RuntimeEvent, ToolPermission
from kratos_agent.core.skills import skill_manager
from kratos_agent.core.tool_runtime import legacy_tool_registry
from kratos_agent.core.subagents import SubagentManager
from kratos_agent.core.project_memory import project_memory
from kratos_agent.core.prompt_library import prompt_library

load_dotenv()
DEFAULT_MODEL = get_default_model()


class KratosRuntime:
    """Composes replaceable instructions, context, tools, provider, loop and session trace."""
    def __init__(self, model_name: str = DEFAULT_MODEL, workspace: Path | None = None) -> None:
        self.workspace = (workspace or Path.cwd()).resolve()
        self.model_name = model_name
        self.skill_manager = skill_manager
        self.memory = memory
        self.instructions = InstructionEngine()
        self._register_instruction_modules()
        self.context = ContextBuilder(ContextBudget())
        self.tools_registry = legacy_tool_registry(self.workspace)
        self.mcp = McpManager(self.workspace / ".kratos" / "mcp.json")
        self.tools = self.tools_registry.specs()  # Existing CLI compatibility.
        self.brain = BrainChatModel(model=self.model_name)
        self.model = BrainAdapter(self.model_name, self.brain.client)
        self.agent = None  # The explicit AgentLoop replaces the opaque LangChain graph.
        self._history = self._restore_history()
        self._event_store = self._open_event_store()
        self.last_request: Dict[str, Any] | None = None
        self._current_tool_calls: List[Dict[str, Any]] = []
        self._cancellation_flag = threading.Event()
        self.loop = AgentLoop(self.context, self.instructions, self.tools_registry, self.model, lambda event: self._emit(event), self.workspace, self._cancellation_flag)
        self.subagents = SubagentManager(self._run_isolated)

    def _register_instruction_modules(self) -> None:
        self.instructions.register(InstructionModule("core-safety", "system", lambda: (
            "You are Kratos, an autonomous terminal coding agent. You directly execute actions using tools. "
            "CRITICAL: Never output statements describing what you will do or intend to do (e.g. 'I will inspect the workspace', 'I am going to create the files') without immediately providing the corresponding tool call in the same response. "
            "Directly invoke tools to perform inspection, file creation, code edits, terminal commands, and verification."
        ), 10))
        self.instructions.register(InstructionModule("developer-workflow", "developer", lambda: (
            "AUTONOMOUS EXECUTION PROTOCOL:\n"
            "1. When a user requests code, scaffolding, or a project, immediately start invoking tools (`write_file`, `run_terminal_command`, `read_file`, `edit_file`).\n"
            "2. Never provide conversational filler or mere intent statements. Always execute actions with actual tool calls (`call:TOOL_NAME{...}`).\n"
            "3. Progress through the plan by executing the required tools for each task until all tasks and verification are complete."
        ), 20))
        self.instructions.register(InstructionModule("workspace", "project", lambda: f"Workspace: {self.workspace}\n{project_memory.get_project_context()}", 30))
        self.instructions.register(InstructionModule("skills", "persona", lambda: self.skill_manager.get_all_skills_prompt(), 40))
        self.instructions.register(InstructionModule("engineering-guidelines", "developer", lambda: prompt_library.get_engineering_guidelines(), 50))

    def _restore_history(self) -> List[ChatMessage]:
        active = self.memory.active_session
        if not active:
            return []
        history: List[ChatMessage] = []
        for turn in active.turns:
            history.extend([ChatMessage("user", str(turn.get("user", ""))), ChatMessage("assistant", str(turn.get("agent", "")))])
        return history

    def _open_event_store(self) -> EventStore:
        session_id = self.memory.active_session.session_id if self.memory.active_session else "default"
        return EventStore(self.workspace / ".kratos" / "sessions" / session_id)

    def activate_session(self) -> None:
        """Rebind runtime history and trace after the session manager switches sessions."""
        self._history = self._restore_history()
        self._event_store = self._open_event_store()

    def _emit(self, event: RuntimeEvent) -> None:
        self._event_store.append(event)
        if event.kind.value == "model.request_assembled":
            self.last_request = event.payload
        elif event.kind.value == "tool.requested":
            self._current_tool_calls.append(event.payload)

    def _run_isolated(self, role: str, history: List[ChatMessage]) -> str:
        """Run a child task with a fresh history and role-scoped instructions."""
        child_instructions = InstructionEngine()
        for section in self.instructions.build():
            child_instructions.register(InstructionModule(section["name"], section["layer"], lambda content=section["content"]: content))
        child_instructions.register(InstructionModule(f"subagent-{role}", "persona", lambda: f"You are a specialized {role} subagent. Return findings and evidence to your parent; do not assume the parent has your context.", 5))
        child_loop = AgentLoop(self.context, child_instructions, self.tools_registry, self.model, self._emit, self.workspace)
        result, _ = child_loop.run(history, self._allow_tool)
        return result

    def cancel(self) -> None:
        """Signal the active agent turn to stop at the next tool boundary."""
        self._cancellation_flag.set()

    def clear_cancel(self) -> None:
        """Clear a pending cancellation so the next turn can run normally."""
        self._cancellation_flag.clear()

    def reload_tools(self) -> None:
        self.tools_registry = legacy_tool_registry(self.workspace)
        self.tools = self.tools_registry.specs()
        self.loop.tools = self.tools_registry

    def set_model(self, model_name: str) -> None:
        self.model_name = model_name
        self.brain = BrainChatModel(model=model_name)
        self.model = BrainAdapter(model_name, self.brain.client)
        self.loop.model = self.model
        if self.memory.active_session:
            self.memory.active_session.model = model_name
            self.memory.save()

    def _allow_tool(self, spec: Any, arguments: Dict[str, Any]) -> tuple[bool, str]:
        if spec.permission == ToolPermission.READ:
            return True, "read-only"
        if spec.permission == ToolPermission.WRITE:
            target = str(arguments.get("file_path", ""))
            resolved = (self.workspace / target).resolve()
            try:
                resolved.relative_to(self.workspace)
            except ValueError:
                return False, "file target escapes workspace"
            return approval_gate.check_write(target), f"write {target}"
        if spec.permission == ToolPermission.EXECUTE:
            return approval_gate.check_shell(str(arguments.get("command", ""))), "shell command"
        if approval_gate.mode == ApprovalMode.SUGGEST:
            return False, f"{spec.permission.value} tools require auto-edit or full-auto mode"
        return True, spec.permission.value

    def invoke(self, messages: List[Dict[str, str]]) -> str:
        self._current_tool_calls = []
        self._cancellation_flag.clear()  # Always start fresh for a new turn
        history = [ChatMessage(role=item.get("role", "user"), content=str(item.get("content", ""))) for item in messages]
        resume_plan = None
        user = next((item.content for item in reversed(history) if item.role == "user"), "")
        if user.strip().lower() in ("continue", "resume", "/continue") and self.memory.active_session:
            resume_plan = self.memory.active_session.get_plan()
        result, final_history = self.loop.run(history, self._allow_tool, resume_plan=resume_plan)
        self._history = final_history

        plan_dict = self.loop.current_plan.to_dict() if self.loop.current_plan else None
        files_dict = self.loop.workspace_tracker.summary() if hasattr(self.loop, "workspace_tracker") else None
        verif_dict = self.loop.last_verification.__dict__ if getattr(self.loop, "last_verification", None) else None
        status = "paused" if self._cancellation_flag.is_set() else "completed"

        self.memory.record_turn(
            user,
            result,
            self._current_tool_calls,
            plan=plan_dict,
            files_changed=files_dict,
            verification_status=verif_dict,
            status=status
        )
        return result

    def run_agent(self, query: str) -> str:
        self._current_tool_calls = []
        self._history.append(ChatMessage("user", query))
        resume_plan = None
        if query.strip().lower() in ("continue", "resume", "/continue") and self.memory.active_session:
            resume_plan = self.memory.active_session.get_plan()
        result, self._history = self.loop.run(self._history, self._allow_tool, resume_plan=resume_plan)

        plan_dict = self.loop.current_plan.to_dict() if self.loop.current_plan else None
        files_dict = self.loop.workspace_tracker.summary() if hasattr(self.loop, "workspace_tracker") else None
        verif_dict = self.loop.last_verification.__dict__ if getattr(self.loop, "last_verification", None) else None
        status = "paused" if self._cancellation_flag.is_set() else "completed"

        self.memory.record_turn(
            query,
            result,
            self._current_tool_calls,
            plan=plan_dict,
            files_changed=files_dict,
            verification_status=verif_dict,
            status=status
        )
        return result

    def debug_context(self) -> Dict[str, Any]:
        """A redacted, developer-facing snapshot of exactly what Kratos sends."""
        return {"session_id": self.memory.active_session.session_id if self.memory.active_session else None, "model": self.model_name, "instructions": self.instructions.build(), "history": [item.to_dict() for item in self._history], "tools": self.tools_registry.schemas(), "last_request": self.last_request, "events": self._event_store.read()[-100:]}


runtime = KratosRuntime()
agent = runtime.agent
brain = runtime.brain
tools = runtime.tools

def run_agent(query: str) -> str:
    return runtime.run_agent(query)

def set_model(model_name: str) -> None:
    runtime.set_model(model_name)

def reload_tools() -> None:
    runtime.reload_tools()

def main() -> None:
    from kratos_agent.cli import main as cli_main
    cli_main()

if __name__ == "__main__":
    main()
