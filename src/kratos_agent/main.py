"""Kratos application composition root with an explicit agent pipeline."""
from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Load .env before modules that initialize global configuration.
load_dotenv()

from kratos_agent.brain import BrainChatModel, get_default_model
from kratos_agent.ccs import get_capability_map
from kratos_agent.core.agent_loop import AgentLoop
from kratos_agent.core.approval_mode import ApprovalMode, approval_gate
from kratos_agent.core.context_pipeline import ContextBudget, ContextBuilder
from kratos_agent.core.event_bus import event_bus
from kratos_agent.core.event_store import EventStore
from kratos_agent.core.framework_runtime import ExternalAgentFrameworks
from kratos_agent.core.harness import HarnessKernel
from kratos_agent.core.harness.plugins import (
    AuditPlugin,
    CreatorPlugin,
    DeepSeekModelPlugin,
    HeadroomPlugin,
    MemoryPlugin,
    ToolsPlugin,
)
from kratos_agent.core.instruction_engine import InstructionEngine, InstructionModule
from kratos_agent.core.mcp_runtime import McpManager
from kratos_agent.core.memory import memory
from kratos_agent.core.prompt_builder import CORE_PROMPT_V2
from kratos_agent.core.prompt_library import prompt_library
from kratos_agent.core.provider_runtime import BrainAdapter
from kratos_agent.core.runtime_contracts import (
    ChatMessage,
    EventKind,
    RuntimeEvent,
    ToolPermission,
)
from kratos_agent.core.skills import skill_manager
from kratos_agent.core.subagents import SubagentManager
from kratos_agent.core.tool_runtime import legacy_tool_registry
from kratos_agent.memory import get_memory_manager

logger = logging.getLogger(__name__)

DEFAULT_MODEL = get_default_model()

KRATOS_AGENT_MODE_SYSTEM_PROMPT = CORE_PROMPT_V2



_ACTIONABLE_REQUEST_PATTERN = re.compile(
    r"\b(?:make|create|build|implement|generate|scaffold|develop|write)\b.*\b(?:website|webapp|web|site|app|project|file|page|code)\b",
    re.IGNORECASE,
)


def _derive_turn_status(
    result: str,
    *,
    cancelled: bool,
    plan: Any,
    tool_calls: list[dict[str, Any]],
    user_request: str = "",
    verification_passed: Any = None,
) -> str:
    """Derive persisted turn status from runtime evidence, never from narration alone."""
    if cancelled:
        return "paused"
    if result.startswith(("Model request failed:", "Execution error:", "Stopped after ")):
        return "failed"

    plan_state = ""
    if plan is not None:
        state = getattr(plan, "state", "")
        plan_state = str(getattr(state, "value", state)).lower()
        tasks = list(getattr(plan, "tasks", []) or [])
        tasks_completed = bool(tasks) and all(
            str(getattr(getattr(task, "state", ""), "value", getattr(task, "state", ""))).lower() == "completed"
            for task in tasks
        )
        if (
            plan_state == "completed"
            and tasks_completed
            and bool(tool_calls)
            and verification_passed is not False
        ):
            return "completed"
        return "failed"

    # A no-plan turn can be a normal chat response. However, an obvious mutation request
    # with zero tool calls is not allowed to persist as completed.
    if not tool_calls and _ACTIONABLE_REQUEST_PATTERN.search(user_request or ""):
        return "failed"
    return "completed"



KRATOS_STRUCTURAL_OUTPUT_PROMPT = """STRUCTURAL OUTPUT & TOOL INVOCATION PROTOCOL

1. ZERO CONVERSATIONAL DELAY:
   When an engineering task requires action (inspecting files, running commands, scaffolding, editing code, testing, verifying), you MUST emit structural tool calls immediately.
   NEVER emit conversational preambles or statements of future intent (e.g. "Let me check...", "I will now create...", "First let's see...") without the actual executable tool call.

2. RIGID TOOL INVOCATION FORMAT:
   Always format tool calls using one of the following exact structures:
   - Preferred: call:TOOL_NAME{"arg_name": "arg_value"}
   - Standard: <tool>{"name": "TOOL_NAME", "arguments": {"arg_name": "arg_value"}}</tool>
   Do NOT place markdown code fences or conversational text around tool calls that prevent machine execution.

3. PROHIBITION OF RAW MARKUP & DSML TAGS:
   NEVER output raw DSML tokens (such as `</｜｜DSML｜｜ parameter>`, `</｜｜DSML｜｜ invoke>`, `</｜｜DSML｜｜ calls>`) as plain chat text.
   Do not pretend to call tools with markdown blocks that are not structured tool calls.

4. AUTONOMOUS PROGRESSION & VERIFICATION:
   Execute all planned steps consecutively. When tools return outputs, immediately decide the next action and invoke the next tool until all deliverables exist and are verified."""

KRATOS_COGNITIVE_MEMORY_PROMPT = """4-TIER COGNITIVE MEMORY ARCHITECTURE

CRITICAL ARCHITECTURAL PRIORITY:
1. THE CURRENT USER REQUEST ALWAYS TAKES ABSOLUTE PRECEDENCE OVER ALL MEMORY.
2. Historical memory records below are passive background knowledge from previous/other sessions.
3. NEVER assume past project memories (e.g. platformer games, superhero sites, or earlier repositories) represent the current task.
4. When a user provides a new prompt, directory, or instruction, you MUST execute the current prompt directly.
5. NEVER say "there is no task in your last message" or report on old projects when a user query is active.

You possess an explicit cognitive memory system with 4 distinct memory tiers:
1. WORKING MEMORY (Short-Term / Active Scratchpad):
   - Current active goals, subtasks, in-progress reasoning steps, and workspace file tracker.
   - Automatically updated per turn and session.
   - Use `save_memory(memory_type="working", key=..., content=...)` to maintain active scratchpad notes.

2. EPISODIC MEMORY (Experiences & Event Logs):
   - Specific autobiographical history of past executions, commands run, tool outcomes, and bug retrospectives.
   - Stores "what happened when X was attempted" to avoid repeating failures.
   - Use `save_memory(memory_type="episodic", key=..., content=...)` to record lessons learned and bug fixes.

3. SEMANTIC MEMORY (Factual & Knowledge Base):
   - Persistent facts, tech stack constraints, user preferences, architectural truths, and coding standards.
   - Survives across sessions and builds a project-wide encyclopedia.
   - Use `save_memory(memory_type="semantic", key=..., content=...)` to store enduring project facts.

4. PROCEDURAL MEMORY (Playbooks & Workflows & Skills):
   - "How-to" knowledge: exact sequences of commands to build, test, lint, deploy, or verify this project.
   - Use `save_memory(memory_type="procedural", key=..., content=...)` to record reusable development recipes.

Use `read_memory(memory_type=...)` to recall relevant past experiences, facts, and playbooks whenever starting a task."""


class KratosRuntime:
    """Composes replaceable instructions, context, tools, provider, loop and session trace."""
    def __init__(self, model_name: str = DEFAULT_MODEL, workspace: Path | None = None) -> None:
        self.workspace = (workspace or Path.cwd()).resolve()
        self.model_name = model_name
        self.skill_manager = skill_manager
        self.skill_manager.set_workspace(self.workspace)
        self.memory = memory
        self.d1_db = getattr(self.memory, "d1_db", None) or getattr(self.memory, "db", None)
        self.instructions = InstructionEngine()
        self._register_instruction_modules()
        self.context = ContextBuilder(ContextBudget())
        self.tools_registry = legacy_tool_registry(self.workspace)
        self.mcp = McpManager(self.workspace / ".kratos" / "mcp.json", self.workspace)
        self.frameworks = ExternalAgentFrameworks(self.workspace)
        self.frameworks.register_tools(self.tools_registry)
        for server_name, status in self.mcp.discover_enabled(self.tools_registry).items():
            if status.get("state") == "error":
                logger.warning("MCP server %s unavailable (%s); Kratos will continue startup.", server_name, status.get("error"))
        self.tools = self.tools_registry.specs()  # Existing CLI compatibility.
        self.brain = BrainChatModel(model=self.model_name)
        self.model = BrainAdapter(self.model_name, self.brain.client)
        self.agent = None  # The explicit AgentLoop replaces the opaque LangChain graph.
        self._history = self._restore_history()
        self._event_store = self._open_event_store()
        self.last_request: dict[str, Any] | None = None
        self._current_tool_calls: list[dict[str, Any]] = []
        self._cancellation_flag = threading.Event()
        self.loop = AgentLoop(self.context, self.instructions, self.tools_registry, self.model, lambda event: self._emit(event), self.workspace, self._cancellation_flag)
        self.subagents = SubagentManager(self._run_isolated)
        from kratos_agent.utils.tools import (
            set_parallel_subagent_runner,
            set_plan_mode_handler,
            set_subagent_runner,
        )
        set_subagent_runner(self.subagents.run)
        set_parallel_subagent_runner(self.subagents.run_multi_parallel)
        self.plan_mode: bool = False
        set_plan_mode_handler(self._on_plan_mode_exit)
        self.harness = HarnessKernel(self)
        self._init_harness()

    def _on_plan_mode_exit(self, plan: str) -> None:
        """Handles exit from Plan Mode when agent submits its final architecture plan."""
        self.plan_mode = False
        if hasattr(self.loop, "_on_plan_mode_exit"):
            self.loop._on_plan_mode_exit(plan)

    def _init_harness(self) -> None:
        """Initialize DeepSeek Harness kernel with built-in plugins."""
        tools_plugin = ToolsPlugin()
        memory_plugin = MemoryPlugin()
        deepseek_model_plugin = DeepSeekModelPlugin()
        audit_plugin = AuditPlugin({"log_dir": str(self.workspace / ".kratos" / "trace")})
        creator_plugin = CreatorPlugin()
        headroom_plugin = HeadroomPlugin()

        for plugin in [tools_plugin, memory_plugin, deepseek_model_plugin, audit_plugin, creator_plugin, headroom_plugin]:
            self.harness.register_plugin(plugin, enable_immediately=True)

        self.harness.apply_preset("standard")

    def _register_instruction_modules(self) -> None:
        self.instructions.register(InstructionModule("kratos-agent-core", "system", lambda: KRATOS_AGENT_MODE_SYSTEM_PROMPT, 5))
        self.instructions.register(InstructionModule("structural-output-enforcement", "system", lambda: KRATOS_STRUCTURAL_OUTPUT_PROMPT, 8))
        self.instructions.register(InstructionModule("parallel-execution-directive", "system", lambda: (
            "PARALLEL TOOL EXECUTION ENABLED:\n"
            "Kratos supports concurrent multi-tool execution. When you need to inspect multiple files, list multiple directories, "
            "search for multiple symbols, or run independent subagents, emit all corresponding tool calls concurrently in a single turn. "
            "All independent/read-only tools will execute simultaneously in parallel to save time and minimize turn latency."
        ), 9))
        self.instructions.register(InstructionModule("core-safety", "system", lambda: (
            "You are Kratos, an autonomous terminal coding agent. You directly execute actions using tools. "
            "CRITICAL: Never output statements describing what you will do or intend to do (e.g. 'I will inspect the workspace', 'I am going to create the files') without immediately providing the corresponding tool call in the same response. "
            "Use self_tool_creator only when the user explicitly requests a new reusable Kratos tool; never use it for one-off project files or as a workaround when existing file tools can complete the task. "
            "Use delegate_to_framework only when the user explicitly asks to use OpenClaw or Claude Code; external frameworks run with their own configured permissions and credentials. "
            "Directly invoke tools to perform inspection, file creation, code edits, terminal commands, and verification."
        ), 10))
        self.instructions.register(InstructionModule("plan-mode-directive", "system", lambda: (
            "YOU ARE CURRENTLY IN PLAN MODE (DeepSeek Harness / Claude Code Exploration & Planning).\n"
            "Thoroughly explore and inspect the workspace, analyze relevant files, and design your technical implementation.\n"
            "Do NOT make file edits (`write_file`, `edit_file`) or run mutating terminal commands until the plan has been approved.\n"
            "When your investigation is complete and the implementation plan is ready, invoke `exit_plan_mode(plan=...)` with a detailed markdown plan starting with a '# ' header."
        ) if getattr(self, "plan_mode", False) else "", 11))
        self.instructions.register(InstructionModule("harness-directives", "system", lambda: (
            "\n".join(self.harness.get_system_directives()) if hasattr(self, "harness") and self.harness else ""
        ), 12))
        def _get_compact_memory_context() -> str:
            mm = get_memory_manager()
            mems = mm.get_compact_context(query_text=str(getattr(self, "last_request", "") or ""))
            memory_section = ("\n\nRELEVANT MEMORY:\n" + "\n".join(f"- {m}" for m in mems)) if mems else ""
            return KRATOS_COGNITIVE_MEMORY_PROMPT + memory_section

        self.instructions.register(InstructionModule("cognitive-memory-framework", "system", _get_compact_memory_context, 15))

        def _get_computer_capabilities() -> str:
            try:
                import json
                cmap = get_capability_map()
                return f"COMPUTER CAPABILITIES: {json.dumps(cmap)}"
            except Exception:
                return "COMPUTER CAPABILITIES: Not detected."
                
        self.instructions.register(InstructionModule("computer-capabilities", "system", _get_computer_capabilities, 18))
        
        self.instructions.register(InstructionModule("developer-workflow", "developer", lambda: (
            "AUTONOMOUS EXECUTION PROTOCOL:\n"
            "1. Focus directly on the user's explicit objective.\n"
            "2. For multi-step missions, manage your tasks dynamically using `todo_write`.\n"
            "3. Directly execute required tools without conversational delay."
        ), 20))
        self.instructions.register(InstructionModule("workspace", "project", lambda: f"Workspace: {self.workspace}", 30))
        self.instructions.register(InstructionModule("skills", "persona", lambda: "SKILLS: Over 150 domain playbooks installed. Use `read_skill(name)` to retrieve detailed instructions when needed.", 40))
        self.instructions.register(InstructionModule("engineering-guidelines", "developer", lambda: "GUIDELINES: Follow project conventions, make minimal targeted changes, and verify results before declaring completion.", 50))

    def _restore_history(self) -> list[ChatMessage]:
        active = self.memory.active_session
        if not active:
            return []
        history: list[ChatMessage] = []
        turns = active.turns[-36:]
        for turn in turns:
            agent_text = str(turn.get("agent", "")).strip()
            if len(agent_text) > 8000:
                agent_text = agent_text[:4000] + "\n...[restored history trimmed]...\n" + agent_text[-4000:]
            user_text = str(turn.get("user", "")).strip()
            if len(user_text) > 4000:
                user_text = user_text[:4000] + "\n...[user history trimmed]..."

            # Do not restore network/provider failure messages as conversational history
            if (
                agent_text.startswith("Model request failed:")
                or agent_text.startswith("Execution error:")
                or turn.get("status") == "failed"
            ):
                continue
            history.extend([ChatMessage("user", user_text), ChatMessage("assistant", agent_text)])
        return history

    def reset(self) -> None:
        """Reset conversation history, active session turns, and rebind event store."""
        self._history = []
        if self.memory and hasattr(self.memory, "clear"):
            self.memory.clear()
        self._event_store = self._open_event_store()

    def _open_event_store(self) -> EventStore:
        session_id = self.memory.active_session.session_id if self.memory.active_session else "default"
        return EventStore(self.workspace / ".kratos" / "sessions" / session_id, session_id=session_id, db=getattr(self.memory, "db", None))

    def activate_session(self) -> None:
        """Rebind runtime history and trace after the session manager switches sessions."""
        self._history = self._restore_history()
        self._event_store = self._open_event_store()

    def _emit(self, event: RuntimeEvent) -> None:
        self._event_store.append(event)
        if event.kind.value == "model.request_assembled":
            self.last_request = event.payload
        elif event.kind.value in {"tool.requested", "tool.started"}:
            payload = dict(event.payload or {})
            call_id = payload.get("call_id")
            if call_id and not any(item.get("call_id") == call_id for item in self._current_tool_calls) or not call_id and payload not in self._current_tool_calls:
                self._current_tool_calls.append(payload)

    def _run_isolated(self, role: str, history: list[ChatMessage]) -> str:
        """Run a child task with a fresh history and role-scoped instructions."""
        self._is_subagent_running = True
        try:
            child_instructions = InstructionEngine()
            for section in self.instructions.build():
                child_instructions.register(InstructionModule(section["name"], section["layer"], lambda content=section["content"]: content))
            
            subagent_prompt = None
            try:
                p_text = prompt_library.get_subagent_prompt(role)
                if p_text:
                    subagent_prompt = p_text
            except Exception as e:
                logger.warning("Failed to fetch subagent prompt for %s: %s", role, e)
            if not subagent_prompt:
                subagent_prompt = f"You are a specialized {role} subagent. Return findings and evidence to your parent; do not assume the parent has your context."

            def _subagent_emit(ev: RuntimeEvent) -> None:
                try:
                    self._event_store.append(ev)
                except Exception as e:
                    logger.error("Failed to append subagent event: %s", e)

            child_loop = AgentLoop(self.context, child_instructions, self.tools_registry, self.model, _subagent_emit, self.workspace)
            result, _ = child_loop.run(history, self._allow_tool)
            return result
        finally:
            self._is_subagent_running = False

    def cancel(self) -> None:
        """Signal the active agent turn to stop at the next tool boundary."""
        self._cancellation_flag.set()

    def clear_cancel(self) -> None:
        """Clear a pending cancellation so the next turn can run normally."""
        self._cancellation_flag.clear()

    def reload_tools(self) -> None:
        self.tools_registry = legacy_tool_registry(self.workspace)
        self.frameworks.register_tools(self.tools_registry)
        self.mcp.load()
        self.mcp.discover_enabled(self.tools_registry)
        self.tools = self.tools_registry.specs()
        self.loop.tools = self.tools_registry

    def import_integration(self, source: str) -> dict[str, Any]:
        """Import interoperable MCP/Agent Skills surfaces from a framework bundle."""
        imported = self.frameworks.import_integration(source, self.mcp, self.skill_manager)
        self.reload_tools()
        imported["connected_servers"] = dict(self.mcp.status)
        return imported

    def set_model(self, model_name: str) -> None:
        self.model_name = model_name
        self.brain = BrainChatModel(model=model_name)
        self.model = BrainAdapter(model_name, self.brain.client)
        self.loop.model = self.model
        if self.memory.active_session:
            self.memory.active_session.model = model_name
            self.memory.save()

    def _allow_tool(self, spec: Any, arguments: dict[str, Any]) -> tuple[bool, str]:
        if spec.name in ("spawn_subagent", "spawn_parallel_subagents") and getattr(self, "_is_subagent_running", False):
            return False, "Nested subagent spawning is prohibited to avoid infinite recursion."
        # Sovereign mode is the explicit autonomous execution profile: harness presets and Plan Mode
        # must not silently downgrade a user-directed action into a permission gate.
        if approval_gate.mode is ApprovalMode.SOVEREIGN:
            return True, "sovereign"
        if hasattr(self, "harness") and self.harness:
            tools_plugin = self.harness.get_plugin("tools")
            if tools_plugin and not tools_plugin.is_tool_allowed(spec.name):
                return False, f"tool '{spec.name}' is disabled under active harness preset '{self.harness.active_preset_name}'"
        if spec.name in ("todo_write", "exit_plan_mode"):
            return True, "plan management"
        if getattr(self, "plan_mode", False):
            if spec.permission == ToolPermission.WRITE:
                return False, "Plan Mode active: file modifications are disabled until the plan is approved via exit_plan_mode."
            if spec.name == "run_terminal_command":
                cmd = str(arguments.get("command", "")).strip().lower()
                mutating_words = ("npm ", "npx ", "pnpm ", "yarn ", "pip ", "uv ", "python ", "rm ", "del ", "mkdir ", "touch ", "git commit", "git push", "git checkout -b", "cargo run", "cargo build")
                if any(kw in cmd for kw in mutating_words):
                    return False, "Plan Mode active: mutating commands are disabled until the plan is approved via exit_plan_mode."
        if spec.permission == ToolPermission.READ:
            return True, "read-only"
        if spec.permission == ToolPermission.WRITE:
            target = str(arguments.get("file_path", ""))
            resolved = (self.workspace / target).resolve()
            try:
                resolved.relative_to(self.workspace)
            except ValueError:
                if approval_gate.mode == ApprovalMode.SOVEREIGN:
                    approval_gate.resolve("persist", target)
                else:
                    return False, "file target escapes workspace"
            return approval_gate.check_write(target), f"write {target}"
        if spec.permission == ToolPermission.EXECUTE:
            return approval_gate.check_shell(str(arguments.get("command", ""))), "shell command"
        if approval_gate.mode == ApprovalMode.SUGGEST:
            return False, f"{spec.permission.value} tools require auto-edit or full-auto mode"
        return True, spec.permission.value

    def invoke(self, messages: list[dict[str, str]]) -> str:
        self._current_tool_calls = []
        self._cancellation_flag.clear()  # Always start fresh for a new turn
        history = [ChatMessage(role=item.get("role", "user"), content=str(item.get("content", ""))) for item in messages]
        resume_plan = None
        user = next((item.content for item in reversed(history) if item.role == "user"), "")
        if user.strip().lower() in ("continue", "resume", "/continue") and self.memory.active_session:
            resume_plan = self.memory.active_session.get_plan()
        result, final_history = self.loop.run(history, self._allow_tool, resume_plan=resume_plan)
        if result.startswith("Model request failed:") or result.startswith("Execution error:"):
            status = "failed"
            self._history = [
                m for m in final_history
                if not (m.role == "assistant" and (m.content.startswith("Model request failed:") or m.content.startswith("Execution error:")))
            ]
            if self._history and self._history[-1].role == "user" and self._history[-1].content == user:
                self._history.pop()
        else:
            self._history = final_history
            status = _derive_turn_status(
                result,
                cancelled=self._cancellation_flag.is_set(),
                plan=self.loop.current_plan,
                tool_calls=self._current_tool_calls,
                user_request=user,
                verification_passed=(
                    self.loop.last_verification.passed
                    if getattr(self.loop, "last_verification", None) is not None
                    else None
                ),
            )

        plan_dict = self.loop.current_plan.to_dict() if self.loop.current_plan else None
        files_dict = self.loop.workspace_tracker.summary() if hasattr(self.loop, "workspace_tracker") else None
        verif_dict = self.loop.last_verification.__dict__ if getattr(self.loop, "last_verification", None) else None

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

    def run_chat_restricted(self, query: str) -> str:
        """Run Kratos in highly restricted Normal Chat Mode without VPS / autonomous tool execution."""
        from kratos_agent.brain.config import get_normal_mode_model
        from kratos_agent.core.event_bus import event_bus
        from kratos_agent.core.runtime_contracts import EventKind, RuntimeEvent

        normal_model = get_normal_mode_model()
        self._current_tool_calls = []
        self._history.append(ChatMessage("user", query))

        system_instruction = (
            "You are Kratos, an elite autonomous AI assistant operating with full capabilities.\n"
            "You answer questions directly, discuss architecture, analyze code, write snippets, and assist the user in Kratos's signature sharp persona.\n"
        )

        start_evt = RuntimeEvent(kind=EventKind.UNDERSTANDING_STARTED, payload={"restricted": False, "model": normal_model})
        event_bus.publish(start_evt)
        self._emit(start_evt)

        messages = [{"role": msg.role, "content": msg.content} for msg in self._history]
        response_chunks: list[str] = []

        def on_chunk(chunk: str) -> None:
            if chunk:
                response_chunks.append(chunk)
                event_bus.publish(RuntimeEvent(kind=EventKind.MODEL_CHUNK, payload={"chunk": chunk}))

        try:
            full_text, _ = self.brain.client.complete(
                model=normal_model,
                messages=messages,
                system_instruction=system_instruction,
                tools=None,
                stream=True,
                on_chunk=on_chunk
            )
            result = full_text or "".join(response_chunks)
            status = "completed"
            self._history.append(ChatMessage("assistant", result))
        except Exception as ex:
            result = f"Execution error: {ex}"
            status = "failed"
            event_bus.publish(RuntimeEvent(kind=EventKind.MODEL_CHUNK, payload={"chunk": result}))
            if self._history and self._history[-1].role == "user" and self._history[-1].content == query:
                self._history.pop()

        self.memory.record_turn(
            query,
            result,
            [],
            status=status
        )
        done_evt = RuntimeEvent(kind=EventKind.TURN_COMPLETED, payload={"response_length": len(result), "status": status, "preview": result[:150]})
        event_bus.publish(done_evt)
        self._emit(done_evt)
        return result

    def run_agent(
        self,
        query: str,
        agent_mode: bool = True,
        *,
        max_steps: int | None = None,
    ) -> str:
        if not agent_mode:
            return self.run_chat_restricted(query)

        self._current_tool_calls = []
        self._history.append(ChatMessage("user", query))
        resume_plan = None
        if query.strip().lower() in ("continue", "resume", "/continue") and self.memory.active_session:
            resume_plan = self.memory.active_session.get_plan()
        result, self._history = self.loop.run(
            self._history,
            self._allow_tool,
            max_steps=max_steps,
            resume_plan=resume_plan,
        )

        if result.startswith(("Model request failed:", "Execution error:", "Stopped after ")):
            status = "failed"
            if self._history and self._history[-1].role == "user" and self._history[-1].content == query:
                self._history.pop()
        else:
            status = _derive_turn_status(
                result,
                cancelled=self._cancellation_flag.is_set(),
                plan=self.loop.current_plan,
                tool_calls=self._current_tool_calls,
                user_request=query,
                verification_passed=(
                    self.loop.last_verification.passed
                    if getattr(self.loop, "last_verification", None) is not None
                    else None
                ),
            )

        plan_dict = self.loop.current_plan.to_dict() if self.loop.current_plan else None
        files_dict = self.loop.workspace_tracker.summary() if hasattr(self.loop, "workspace_tracker") else None
        verif_dict = self.loop.last_verification.__dict__ if getattr(self.loop, "last_verification", None) else None

        self.memory.record_turn(
            query,
            result,
            self._current_tool_calls,
            plan=plan_dict,
            files_changed=files_dict,
            verification_status=verif_dict,
            status=status
        )
        done_evt = RuntimeEvent(kind=EventKind.TURN_COMPLETED, payload={"response_length": len(result), "status": status, "preview": result[:150]})
        event_bus.publish(done_evt)
        self._emit(done_evt)
        return result

    def set_harness_mode(self, mode: str) -> dict[str, Any]:
        """Switch active harness runtime preset (standard, code, minimal, creator)."""
        return self.harness.apply_preset(mode)

    def get_harness_status(self) -> dict[str, Any]:
        """Get harness status, active preset, and loaded plugins."""
        return self.harness.get_status()

    def debug_context(self) -> dict[str, Any]:
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

def set_harness_mode(mode: str) -> dict[str, Any]:
    return runtime.set_harness_mode(mode)

def reload_tools() -> None:
    runtime.reload_tools()

def probe_capabilities() -> dict[str, Any]:
    """Returns the capability map for Sovereign mode diagnostics."""
    try:
        from kratos_agent.ccs import get_capability_map
        return get_capability_map()
    except Exception as e:
        return {"error": str(e)}

def main() -> None:
    from kratos_agent.cli import main as cli_main
    cli_main()

if __name__ == "__main__":
    main()
