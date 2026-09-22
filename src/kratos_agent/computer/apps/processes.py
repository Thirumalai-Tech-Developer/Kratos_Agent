"""Process management and resource sampling using psutil."""
from __future__ import annotations
import os
from typing import Any, Dict, List, Optional

from kratos_agent.computer.state import ActionResult

try:
    import psutil
except ImportError:
    psutil = None


class ProcessManager:
    """Monitors, queries, and manages OS processes."""

    def list_processes(self, filter_query: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Lists running processes with PID, name, memory, and CPU metrics."""
        if not psutil:
            return []

        procs: List[Dict[str, Any]] = []
        q_lower = filter_query.lower() if filter_query else None

        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
            try:
                info = p.info
                name = info.get("name") or ""
                if q_lower and q_lower not in name.lower():
                    continue
                mem_rss = info["memory_info"].rss if info.get("memory_info") else 0
                procs.append({
                    "pid": info["pid"],
                    "name": name,
                    "cpu_percent": info.get("cpu_percent", 0.0),
                    "memory_mb": round(mem_rss / (1024 * 1024), 1),
                })
                if len(procs) >= limit:
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        return procs

    def terminate(self, pid: Optional[int] = None, name: Optional[str] = None, force: bool = False) -> ActionResult:
        """Terminates or kills a process by PID or name."""
        if not psutil:
            return ActionResult(ok=False, action="process_terminate", detail="psutil not available")

        # By PID
        if pid is not None:
            try:
                p = psutil.Process(pid)
                if force:
                    p.kill()
                else:
                    p.terminate()
                return ActionResult(ok=True, action="process_terminate", data={"pid": pid, "force": force})
            except Exception as e:
                return ActionResult(ok=False, action="process_terminate", detail=str(e))

        # By name
        if name is not None:
            terminated_pids = []
            name_lower = name.lower()
            for p in psutil.process_iter(["pid", "name"]):
                try:
                    if (p.info.get("name") or "").lower() == name_lower:
                        if force:
                            p.kill()
                        else:
                            p.terminate()
                        terminated_pids.append(p.pid)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            return ActionResult(ok=bool(terminated_pids), action="process_terminate", data={"name": name, "terminated_pids": terminated_pids})

        return ActionResult(ok=False, action="process_terminate", detail="Specify either pid or name")

    def get_resources(self, pid: Optional[int] = None) -> Dict[str, Any]:
        """Gets CPU and memory resources for a process or the system."""
        if not psutil:
            return {}
        try:
            p = psutil.Process(pid) if pid else psutil.Process()
            return {
                "pid": p.pid,
                "name": p.name(),
                "cpu_percent": p.cpu_percent(),
                "memory_mb": round(p.memory_info().rss / (1024 * 1024), 1),
            }
        except Exception as e:
            return {"error": str(e)}


_process_manager: Optional[ProcessManager] = None


def get_process_manager() -> ProcessManager:
    global _process_manager
    if _process_manager is None:
        _process_manager = ProcessManager()
    return _process_manager
