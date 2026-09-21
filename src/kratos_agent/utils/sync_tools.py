import json
import inspect
from pathlib import Path
from kratos_agent.utils import computer_tools

def update_tools_list():
    tools_list_path = Path("src/kratos_agent/utils/tools_list.json")
    data = json.loads(tools_list_path.read_text(encoding="utf-8")) if tools_list_path.exists() else {"tools": []}
    existing_tools = {t["name"]: t for t in data.get("tools", [])}

    # Inspect all functions in computer_tools
    for name in dir(computer_tools):
        if name.startswith("_"):
            continue
        fn = getattr(computer_tools, name)
        if not callable(fn):
            continue

        doc = inspect.getdoc(fn) or f"Executes {name}."
        sig = inspect.signature(fn)
        props = {}
        required = []
        for p in sig.parameters.values():
            if p.name in ("self", "cls"):
                continue
            p_type = "string"
            if p.annotation == int or p.annotation == Optional[int]:
                p_type = "integer"
            elif p.annotation == bool or p.annotation == Optional[bool]:
                p_type = "boolean"
            elif p.annotation == float or p.annotation == Optional[float]:
                p_type = "number"
            elif "List" in str(p.annotation) or "list" in str(p.annotation):
                p_type = "array"
            elif "dict" in str(p.annotation) or "Dict" in str(p.annotation):
                p_type = "object"

            props[p.name] = {"type": p_type, "description": p.name.replace("_", " ")}
            if p.default is inspect.Parameter.empty:
                required.append(p.name)

        tool_def = {
            "name": name,
            "description": doc.split("\n")[0] if doc else f"Executes {name}.",
            "func_name": name,
            "parameters": {
                "type": "object",
                "properties": props,
                "required": required,
            }
        }
        existing_tools[name] = tool_def

    data["tools"] = list(existing_tools.values())
    tools_list_path.write_text(json.dumps(data, indent=4), encoding="utf-8")
    print(f"Total tools in tools_list.json: {len(data['tools'])}")

if __name__ == "__main__":
    from typing import Optional
    update_tools_list()
