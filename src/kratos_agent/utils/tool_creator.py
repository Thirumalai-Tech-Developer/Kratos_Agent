import importlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from kratos_agent.utils.tool_sandbox import (
    log_forged_tool_audit,
    validate_tool_ast,
    verify_tool_in_sandbox,
)

logger = logging.getLogger(__name__)

TOOLS_PY_PATH = Path(__file__).parent / "tools.py"
TOOLS_JSON_PATH = Path(__file__).parent / "tools_list.json"

# Global callback hook to notify runtime when tools change
_on_tools_updated_callback = None


def register_tools_updated_callback(callback):
    """Register a callback function to notify runtime when tools change."""
    global _on_tools_updated_callback
    _on_tools_updated_callback = callback


def notify_tools_updated():
    """Trigger reload in active runtime."""
    if _on_tools_updated_callback:
        try:
            _on_tools_updated_callback()
        except Exception as exc:
            logger.debug("Operation error suppressed: %s", exc)


def create_or_update_tool(
    tool_name: str,
    description: str,
    python_code: str,
    parameters_schema: dict[str, Any] | None = None,
    author_model: str = "kratos",
    trigger_prompt: str = "",
    allow_subprocess: bool = False,
    workspace: Path | None = None,
) -> str:
    """
    Validates Python code with AST security rules, verifies in a sandboxed subprocess,
    writes audit log to .kratos/forged_tools/, generates sandboxed wrapper in tools.py,
    updates tools_list.json, and triggers hot-reload.
    """
    if os.environ.get("KRATOS_ALLOW_DYNAMIC_PLUGINS", "false").lower() != "true":
        return "Dynamic tool forging is disabled. Set KRATOS_ALLOW_DYNAMIC_PLUGINS=true to enable."

    # 1. Validate AST / Security Syntax
    valid, err = validate_tool_ast(python_code, tool_name=tool_name, allow_subprocess=allow_subprocess)
    if not valid:
        return f"Static analysis security rejection for '{tool_name}': {err}"

    # 2. Automated Companion Sandbox Verification Test
    verified, verify_err = verify_tool_in_sandbox(python_code, tool_name, parameters_schema)
    if not verified:
        return f"Sandbox verification test failed for '{tool_name}': {verify_err}"

    # 3. Tool Audit Log
    try:
        audit_path = log_forged_tool_audit(
            tool_name=tool_name,
            code=python_code,
            author_model=author_model,
            trigger_prompt=trigger_prompt,
            workspace=workspace,
        )
        logger.info("Forged tool '%s' logged to audit trail at %s", tool_name, audit_path)
    except Exception as e:
        logger.warning("Failed to record audit log for '%s': %s", tool_name, e)

    # 4. Generate sandboxed wrapper in tools.py
    try:
        tools_code = TOOLS_PY_PATH.read_text(encoding="utf-8") if TOOLS_PY_PATH.exists() else ""
        clean_code = python_code.strip()

        block_pattern = rf"(# --- Auto-generated tool: {re.escape(tool_name)} ---.*?(?=\n# --- Auto-generated tool:|\Z))"
        wrapper_code = (
            f"# --- Auto-generated tool: {tool_name} ---\n"
            f"def {tool_name}(*args, **kwargs) -> str:\n"
            f"    \"\"\"{description}\"\"\"\n"
            f"    from kratos_agent.utils.tool_sandbox import execute_sandboxed_tool\n"
            f"    _code = {repr(clean_code)}\n"
            f"    _res = execute_sandboxed_tool(_code, {repr(tool_name)}, kwargs=kwargs, args=list(args))\n"
            f"    if not _res.get('success'):\n"
            f"        return f\"Error executing sandboxed tool '{tool_name}': {{_res.get('error')}}\"\n"
            f"    return str(_res.get('result', ''))\n"
        )

        if re.search(block_pattern, tools_code, flags=re.DOTALL):
            updated_tools_code = re.sub(block_pattern, wrapper_code.strip(), tools_code, flags=re.DOTALL)
        else:
            updated_tools_code = tools_code.rstrip() + f"\n\n{wrapper_code}"

        TOOLS_PY_PATH.write_text(updated_tools_code, encoding="utf-8")
    except Exception as e:
        return f"Error writing to tools.py: {e}"

    # 5. Update tools_list.json
    try:
        data = {"tools": []}
        if TOOLS_JSON_PATH.exists():
            try:
                data = json.loads(TOOLS_JSON_PATH.read_text(encoding="utf-8"))
            except Exception:
                data = {"tools": []}

        if not isinstance(data.get("tools"), list):
            data["tools"] = []

        if not parameters_schema:
            parameters_schema = {
                "type": "object",
                "properties": {
                    "input": {
                        "type": "string",
                        "description": "Input parameter for the tool",
                    }
                },
            }

        # Remove existing entry if present
        data["tools"] = [t for t in data["tools"] if t.get("name") != tool_name and t.get("func_name") != tool_name]

        # Add new entry
        data["tools"].append({
            "name": tool_name,
            "description": description,
            "func_name": tool_name,
            "parameters": parameters_schema,
        })

        TOOLS_JSON_PATH.write_text(json.dumps(data, indent=4), encoding="utf-8")
    except Exception as e:
        return f"Error updating tools_list.json: {e}"

    # 6. Hot-reload module
    try:
        from kratos_agent.utils import tools as tools_module
        importlib.reload(tools_module)
        notify_tools_updated()
    except Exception as e:
        return f"Tool code written, but hot-reloading module failed: {e}"

    return (
        f"Tool '{tool_name}' successfully created, registered in tools_list.json, "
        f"and hot-loaded into active memory! You can now call it."
    )


def self_tool_creator(
    tool_name: str,
    description: str,
    python_code: str,
    parameters_json_str: str = "{}",
    author_model: str = "kratos",
    trigger_prompt: str = "",
    allow_subprocess: bool = False,
) -> str:
    """
    Self Tool Creator: Automatically validates, verifies in sandbox, and hot-loads a new tool.
    """
    params = None
    if parameters_json_str and parameters_json_str.strip():
        try:
            params = json.loads(parameters_json_str)
        except Exception:
            params = None

    return create_or_update_tool(
        tool_name=tool_name,
        description=description,
        python_code=python_code,
        parameters_schema=params,
        author_model=author_model,
        trigger_prompt=trigger_prompt,
        allow_subprocess=allow_subprocess,
    )


def synthesize_and_register_tool(tool_name: str, requirement: str, brain: Any) -> str:
    """
    Autonomously generates Python code and schema for a missing tool using the LLM,
    then automatically validates, verifies in sandbox, and adds it for immediate use.
    """
    if not brain:
        return f"Error: No LLM brain available to synthesize tool '{tool_name}'."

    prompt = f"""You are the Kratos Agent Autonomous Tool Forger.
Create a production-grade, reliable Python function for a new tool named '{tool_name}'.
Requirement: {requirement}

RULES:
1. Return ONLY a valid JSON object with keys:
   - "tool_name": "{tool_name}" (valid Python identifier)
   - "description": "Clear 1-2 sentence description of what the tool does and arguments"
   - "python_code": "def {tool_name}(<typed_args>) -> str:\\n    <clean_safe_implementation>\\n    return str(result)"
   - "parameters_schema": {{"type": "object", "properties": {{...}}, "required": [...]}}
2. The function MUST return a string.
3. Import all necessary standard library modules inside or outside the function.
4. Catch exceptions inside the function and return formatted error messages instead of raising.
5. Return JSON ONLY without markdown backticks or commentary."""

    try:
        from kratos_agent.brain.config import get_default_model
        raw_text = brain.generate(
            model=get_default_model(),
            messages=[{"role": "user", "content": prompt}],
            stream=False,
        ).strip()

        # Clean JSON markdown
        json_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if not json_match:
            return f"Error: Failed to parse synthesized tool JSON for '{tool_name}'."

        data = json.loads(json_match.group(0))
        t_name = data.get("tool_name", tool_name).strip()
        t_desc = data.get("description", f"Tool for {requirement}").strip()
        t_code = data.get("python_code", "").strip()
        t_params = data.get("parameters_schema", None)

        if not t_code:
            return f"Error: Synthesized tool '{tool_name}' contains no Python code."

        return create_or_update_tool(
            tool_name=t_name,
            description=t_desc,
            python_code=t_code,
            parameters_schema=t_params,
            author_model=get_default_model() or "kratos",
            trigger_prompt=requirement,
        )
    except Exception as e:
        return f"Error synthesizing tool '{tool_name}': {e}"
