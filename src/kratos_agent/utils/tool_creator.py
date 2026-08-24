import ast
import re
import json
import importlib
from pathlib import Path
from typing import Dict, Any, Optional

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
        except Exception:
            pass

def create_or_update_tool(
    tool_name: str,
    description: str,
    python_code: str,
    parameters_schema: Optional[Dict[str, Any]] = None
) -> str:
    """
    Validates Python code, writes the function to tools.py,
    updates tools_list.json, and triggers a hot-reload.
    """
    # 1. Validate AST / Syntax
    try:
        parsed_ast = ast.parse(python_code)
    except SyntaxError as e:
        return f"Error: Python syntax validation failed on line {e.lineno}: {e.msg}"

    # Check that the function is actually defined in the provided code
    defined_funcs = [
        node.name for node in ast.walk(parsed_ast)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    if tool_name not in defined_funcs:
        return (
            f"Error: Provided python_code does not define a function named '{tool_name}'. "
            f"Found functions: {defined_funcs}"
        )

    # 2. Append/Update tools.py
    try:
        tools_code = TOOLS_PY_PATH.read_text(encoding="utf-8") if TOOLS_PY_PATH.exists() else ""
        clean_code = python_code.strip()
        
        # Pattern matching the tool block
        block_pattern = rf"(# --- Auto-generated tool: {re.escape(tool_name)} ---.*?(?=\n# --- Auto-generated tool:|\Z))"
        new_block = f"# --- Auto-generated tool: {tool_name} ---\n{clean_code}\n"
        
        if re.search(block_pattern, tools_code, flags=re.DOTALL):
            updated_tools_code = re.sub(block_pattern, new_block.strip(), tools_code, flags=re.DOTALL)
        else:
            updated_tools_code = tools_code.rstrip() + f"\n\n{new_block}"

        TOOLS_PY_PATH.write_text(updated_tools_code, encoding="utf-8")
    except Exception as e:
        return f"Error writing to tools.py: {e}"

    # 3. Update tools_list.json
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
                        "description": "Input parameter for the tool"
                    }
                }
            }

        # Remove existing entry if present
        data["tools"] = [t for t in data["tools"] if t.get("name") != tool_name and t.get("func_name") != tool_name]

        # Add new entry
        data["tools"].append({
            "name": tool_name,
            "description": description,
            "func_name": tool_name,
            "parameters": parameters_schema
        })

        TOOLS_JSON_PATH.write_text(json.dumps(data, indent=4), encoding="utf-8")
    except Exception as e:
        return f"Error updating tools_list.json: {e}"

    # 4. Hot-reload module
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
    parameters_json_str: str = "{}"
) -> str:
    """
    Self Tool Creator: Automatically creates, registers, and hot-loads a new Python tool.
    
    Args:
        tool_name: Unique function name (e.g. 'calculate_expression', 'fetch_weather')
        description: Clear explanation of what the tool does and when to call it
        python_code: Complete Python function code defining `def <tool_name>(...): -> str`
        parameters_json_str: JSON string of parameters schema (optional)
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
        parameters_schema=params
    )

def synthesize_and_register_tool(tool_name: str, requirement: str, brain: Any) -> str:
    """
    Autonomously generates Python code and schema for a missing tool using the LLM,
    then automatically adds it to tools.py and tools_list.json for immediate and future use.
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
        from langchain_core.messages import HumanMessage
        response = brain.invoke([HumanMessage(content=prompt)])
        raw_text = getattr(response, "content", str(response)).strip()
        
        # Clean JSON markdown
        json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
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
            parameters_schema=t_params
        )
    except Exception as e:
        return f"Error synthesizing tool '{tool_name}': {e}"

