"""Synchronize the callable tool catalog without registering imported classes/types."""
from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

import inspect
import json
from pathlib import Path
from typing import Any

from kratos_agent.computer import tools as computer_tool_package
from kratos_agent.utils import computer_tools
from kratos_agent.utils import tools as legacy_tools

_EXCLUDED = {
    "read_notifications","volume_control","wifi_control","bluetooth_control","hosts_file_edit",
    "firewall_rule","shortcut_create","ui_invoke","self_install_capability","browser_tab",
}

def _json_type(annotation: Any) -> str:
    text = str(annotation).lower()
    if "bool" in text: return "boolean"
    if "int" in text: return "integer"
    if "float" in text or "decimal" in text: return "number"
    if "list" in text or "sequence" in text or "tuple" in text: return "array"
    if "dict" in text or "mapping" in text or "object" in text: return "object"
    return "string"

def _iter_tool_functions() -> dict[str, Any]:
    found: dict[str, Any] = {}
    for module in (legacy_tools, computer_tools, computer_tool_package):
        for name, fn in inspect.getmembers(module, inspect.isfunction):
            if name.startswith("_") or name in _EXCLUDED:
                continue
            module_ok = fn.__module__ == module.__name__
            if module is computer_tool_package:
                module_ok = module_ok or fn.__module__.startswith(module.__name__ + ".")
            if not module_ok:
                continue
            found[name] = fn
    return found

def update_tools_list() -> None:
    """Regenerate tools_list.json from actual Python functions only."""
    tools_list_path = Path(__file__).resolve().parent / "tools_list.json"
    existing = {}
    if tools_list_path.exists():
        try:
            existing = {x.get("name") or x.get("func_name"): x for x in json.loads(tools_list_path.read_text(encoding="utf-8")).get("tools", [])}
        except Exception as exc:
            logger.debug("Operation error suppressed: %s", exc)
    output=[]
    for name, fn in sorted(_iter_tool_functions().items()):
        properties, required = {}, []
        for p in inspect.signature(fn).parameters.values():
            if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD): continue
            properties[p.name]={"type":_json_type(p.annotation),"description":p.name.replace("_"," ")}
            if p.default is inspect.Parameter.empty: required.append(p.name)
        old=existing.get(name,{})
        output.append({
            "name":name,
            "description":old.get("description") or (inspect.getdoc(fn) or f"Executes {name}.").split("\n")[0],
            "func_name":name,
            "parameters":{"type":"object","properties":properties,"required":required,"additionalProperties":False},
        })
    tools_list_path.write_text(json.dumps({"tools":output},indent=4,ensure_ascii=False)+"\n",encoding="utf-8")
    print(f"Total callable tools in tools_list.json: {len(output)}")

if __name__ == "__main__":
    update_tools_list()
