from __future__ import annotations

from typing import Any, Dict


class WindowsUIExecutor:
    async def click(self, target: Dict[str, Any]) -> Dict[str, Any]:
        from kratos_agent.computer.gui.resolver import get_resolver
        element = get_resolver().resolve(target)
        backend = element.backend
        return {"ok": bool(element), "verified": bool(element), "backend": backend, "target": target}
