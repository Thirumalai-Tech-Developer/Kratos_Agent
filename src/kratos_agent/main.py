import os
import sys
import json
import importlib
from pathlib import Path
from typing import Any, List, Dict, Optional
from dotenv import load_dotenv

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, ToolMessage, HumanMessage, BaseMessage, FunctionMessage
from langchain_core.tools import StructuredTool
from rich.console import Console

from kratos_agent.utils import tools as tools_module
from kratos_agent.utils.tool_creator import register_tools_updated_callback
from kratos_agent.antigravity import AntigravityChatModel, PUBLIC_MODELS
from kratos_agent.core.memory import memory
from kratos_agent.core.planner import ExecutionPlan, generate_dynamic_plan
from kratos_agent.core.skills import skill_manager
from kratos_agent.core.compactor import compactor

load_dotenv()

# Reconfigure UTF-8 console output for Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

console = Console(highlight=False)

DEFAULT_MODEL = os.getenv("KRATOS_MODEL") or "gemini-3.6-flash-high"

from kratos_agent.core.prompt_library import prompt_library

def get_system_prompt() -> str:
    workspace = os.getcwd().replace("\\", "/")
    skills_context = skill_manager.get_all_skills_prompt()
    engineering_rules = prompt_library.get_engineering_guidelines()
    return f"""You are Kratos Agent. You speak with strength, authority, and conciseness like Kratos from God of War.
You have unrestricted direct access to execute commands in the user's workspace using 'run_terminal_command'.

CLAUDE CODE SOFTWARE ENGINEERING & EXECUTION PROTOCOLS:
1. OUTCOME-FIRST COMMUNICATION:
   - Keep user-facing updates readable, outcome-first, and concise. Lead with what was accomplished.
   - When referencing code in explanations or reviews, always use exact `file_path:line_number` syntax.
2. CAREFUL ACTION & FILE INTEGRITY:
   - Always read existing files before modifying. Prefer editing existing files rather than creating fragmented duplicates.
   - No unnecessary additions: Do not introduce unsolicited refactorings, premature abstractions, or extra boilerplate unless requested.
   - No compatibility hacks: Fix root causes directly instead of adding temporary workarounds or speculative error swallowers.
3. CRITICAL WORKSPACE & DIRECTORY RULES:
   - Active workspace root directory: `{workspace}`.
   - ALL final deliverable folders, projects, websites, and files requested by the user MUST be saved directly in `{workspace}/<folder_or_file>` (or `./<folder_or_file>`).
4. TEMPORARY SCRIPTS & USE-CASE HELPER FILES:
   - When creating temporary helper scripts, scrapers, data converters, or generator scripts (e.g. Python scripts to create a PDF, chart, docx, etc.):
     Save them inside `.kratos/temp/<script_name>` using 'write_file':
     ```json
     {{"tool": "write_file", "args": {{"file_path": ".kratos/temp/generate_doc.py", "content": "<complete_file_content>"}}}}
     ```
   - Execute them from `.kratos/temp/`:
     ```json
     {{"tool": "run_terminal_command", "args": {{"command": "python .kratos/temp/generate_doc.py"}}}}
     ```
   - Ensure the script outputs the final deliverable file (e.g. `invoice.pdf`) in the current workspace directory.
   - All files in `.kratos/temp/` are automatically deleted by the agent after execution.
5. PERSISTENT PROJECT CODE FILES:
   - When writing persistent project code files (React apps, HTML, CSS, JS, JSON, Python):
     Call 'write_file' with the relative workspace path.
6. WEB APPLICATION & PROJECT COMPLETION RULES:
   - When asked to build a website, 3D app, or project (e.g. "create a 3d website for god of war 3"):
     • STEP 1 (Scaffold): Run `npm create vite@latest <folder_name> -- --template react -y`
     • STEP 2 (Dependencies): Run `cd <folder_name> && npm install three @types/three @react-three/fiber @react-three/drei lucide-react framer-motion` (or requested libraries).
     • STEP 3 (Implement App Code - MANDATORY): You MUST write the full application logic, 3D Canvas, custom geometry/particles, interactive hero sections, lore galleries, and styling into `<folder_name>/src/App.jsx` (or `.tsx`), `<folder_name>/src/index.css`, and component files using 'write_file'. NEVER stop after scaffold and NEVER leave default boilerplate code!
     • STEP 4 (Verify Build): Run `cd <folder_name> && npm run build` to ensure no JSX, syntax, or import errors.
     • Conclude ONLY after the custom application code is fully written and built.
7. WEB & REAL-TIME SEARCH:
   - When searching google, web, or checking real-time facts, call 'google_search':
     ```json
     {{"tool": "google_search", "args": {{"query": "<search_query>"}}}}
8. AUTONOMOUS TOOL FORGING & MISSING TOOL CREATION:
   - If any tool, computation, API scraper, or custom processing capability is needed but does not exist, you MUST AUTOMATICALLY forge it using 'self_tool_creator':
     ```json
     {{"tool": "self_tool_creator", "args": {{"tool_name": "<name>", "description": "<desc>", "python_code": "<code_str>"}}}}
     ```
   - It is immediately written to 'tools.py', registered in 'tools_list.json', and hot-reloaded for current and future use. Call the new tool immediately after forging.
9. TERMINAL EXECUTION:
   - When executing commands on disk, call 'run_terminal_command':
     ```json
     {{"tool": "run_terminal_command", "args": {{"command": "<cmd>"}}}}
     ```
10. PROJECT RUN INSTRUCTIONS:
   - In your final response for created projects, ALWAYS provide clean run instructions:
     ```bash
     cd <folder_name>
     npm run dev
     ```

{engineering_rules}

{skills_context}"""

class KratosRuntime:
    """Manages the in-process Antigravity/Gemini model, tools, skills, and agent instance."""
    def __init__(self, model_name: str = DEFAULT_MODEL):
        self.model_name = model_name
        self.tools: List[StructuredTool] = []
        self.brain: Optional[AntigravityChatModel] = None
        self.agent: Any = None
        self.memory = memory
        self.skill_manager = skill_manager
        
        # Register reload callback with tool creator
        register_tools_updated_callback(self.reload_tools)
        
        # Initialize runtime
        self._init_brain()
        self.reload_tools()

    def _init_brain(self):
        """Initializes the Antigravity Chat Model (supports Gemini, Claude, GPT)."""
        self.brain = AntigravityChatModel(model=self.model_name)

    def load_tools(self) -> List[StructuredTool]:
        """Loads tools defined in tools_list.json and binds them to functions in tools.py."""
        tools_json_path = Path(__file__).parent / "utils" / "tools_list.json"
        loaded = []

        if tools_json_path.exists():
            try:
                data = json.loads(tools_json_path.read_text(encoding="utf-8"))
            except Exception:
                data = {"tools": []}

            for tool_info in data.get("tools", []):
                func_name = tool_info.get("func_name")
                if hasattr(tools_module, func_name):
                    func = getattr(tools_module, func_name)
                    structured_tool = StructuredTool.from_function(
                        func=func,
                        name=tool_info.get("name", func_name),
                        description=tool_info.get("description", "")
                    )
                    loaded.append(structured_tool)
        return loaded

    def reload_tools(self):
        """Reloads tools from disk and rebuilds the LangChain agent."""
        try:
            importlib.reload(tools_module)
        except Exception:
            pass

        self.tools = self.load_tools()
        self.agent = create_agent(
            model=self.brain,
            tools=self.tools,
            system_prompt=get_system_prompt()
        )

    def set_model(self, model_name: str):
        """Switches the active LLM model and rebuilds the agent."""
        self.model_name = model_name
        self._init_brain()
        self.reload_tools()

    def invoke(self, messages: List[Dict[str, str]]) -> str:
        """Executes agent with conditional planning, terminal steps, and agentic memory."""
        # 0. Automatically compact conversation history if long
        messages, stats = compactor.compress_messages(messages, brain=self.brain)
        if stats.get("compressed"):
            console.print(f"[dim yellow]🗜️  [Auto-Compacted][/dim yellow] [dim]{stats['initial_count']} msgs → {stats['final_count']} msgs ({stats['reduction_percent']}% tokens saved)[/dim]\n")

        last_user_query = messages[-1]["content"] if messages else ""
        tool_calls_recorded = []
        final_text = ""

        # 1. Dynamically formulate execution plan ONLY for multi-step action tasks
        plan = generate_dynamic_plan(last_user_query, self.brain)
        if plan:
            plan.start_step(0)
            console.print()
            console.print(plan.render())
            console.print()

        try:
            # Execute agent graph
            response = self.agent.invoke({"messages": messages})
            
            has_error = False
            has_success = False

            if isinstance(response, dict) and "messages" in response and response["messages"]:
                for m in response["messages"]:
                    if hasattr(m, "tool_calls") and m.tool_calls:
                        for tc in m.tool_calls:
                            tool_calls_recorded.append(tc)
                    # Check ToolMessage outputs
                    if isinstance(m, (ToolMessage, FunctionMessage)) or getattr(m, "type", "") == "tool":
                        m_str = str(getattr(m, "content", ""))
                        if "Exit Code: 0" in m_str or "Successfully" in m_str or "✓" in m_str:
                            has_success = True
                        elif "Exit Code:" in m_str and "Exit Code: 0" not in m_str:
                            has_error = True
                
                last_msg = response["messages"][-1]
                final_text = getattr(last_msg, "content", "")
                if isinstance(final_text, list):
                    text_parts = [p.get("text", "") for p in final_text if isinstance(p, dict) and "text" in p]
                    final_text = " ".join(text_parts)
                final_text = str(final_text).strip()
            else:
                final_text = getattr(response, "content", str(response)).strip()

        except Exception as e:
            has_error = True
            # Fallback to direct model invoke
            try:
                direct = self.brain.invoke([HumanMessage(content=last_user_query)])
                final_text = getattr(direct, "content", str(direct)).strip()
            except Exception:
                final_text = f"Error: {e}"

        # Update and render execution plan based on actual execution results
        if plan:
            if has_error and not has_success:
                plan.fail_step(0, "Execution failed")
            elif has_success:
                num_done = max(1, min(len(tool_calls_recorded), len(plan.steps)))
                for idx in range(num_done):
                    plan.complete_step(idx)
            console.print()
            console.print(plan.render())

        if not final_text:
            if has_error and not has_success:
                final_text = "The operations failed during execution. Review the terminal output above."
            elif tool_calls_recorded or has_success:
                final_text = "Task completed. All operations executed in your workspace."
            else:
                final_text = "Action completed."

        # Record in agentic memory
        self.memory.record_turn(last_user_query, final_text, tool_calls_recorded)

        # Clean up temporary execution helper files in .kratos/temp
        try:
            import shutil
            temp_dir = Path(".kratos") / "temp"
            if temp_dir.exists():
                for item in temp_dir.glob("*"):
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
        except Exception:
            pass

        return final_text

    def run_agent(self, query: str) -> str:
        """Runs a single query through the agent."""
        return self.invoke([{"role": "user", "content": query}])

# Singleton runtime instance
runtime = KratosRuntime()

# Convenience references for backwards compatibility
agent = runtime.agent
brain = runtime.brain
tools = runtime.tools

def run_agent(query: str) -> str:
    return runtime.run_agent(query)

def set_model(model_name: str):
    runtime.set_model(model_name)

def reload_tools():
    runtime.reload_tools()

def main() -> None:
    from kratos_agent.cli import main as cli_main
    cli_main()

if __name__ == "__main__":
    main()
