import sys
import time
import importlib
from pathlib import Path
from typing import List, Dict, Optional, Set
from rich.console import Console

console = Console(highlight=False)

MODULES_IN_ORDER = [
    "kratos_agent.brain.config",
    "kratos_agent.brain.fetch_model",
    "kratos_agent.brain.client",
    "kratos_agent.brain.chat_model",
    "kratos_agent.brain.brain",
    "kratos_agent.brain",
    "kratos_agent.utils.tools",
    "kratos_agent.utils.tool_creator",
    "kratos_agent.core.planner",
    "kratos_agent.core.memory",
    "kratos_agent.core.skills",
    "kratos_agent.core.compactor",
    "kratos_agent.core.prompt_library",
    "kratos_agent.main",
]

IGNORED_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    "dist", "build", ".next", ".turbo", ".kratos/sessions", ".kratos/temp",
    ".cache", ".pytest_cache"
}

class CodeReloader:
    """Watches Kratos codebase and auto-reloads modules on change during runtime with zero-lag throttling."""

    def __init__(self, watch_roots: Optional[List[Path]] = None):
        if watch_roots is None:
            base_dir = Path(__file__).resolve().parent.parent
            self.watch_roots = [
                base_dir,
                Path(".kratos") / "skills",
            ]
        else:
            self.watch_roots = watch_roots

        self.file_mtimes: Dict[str, float] = {}
        self.last_check_time: float = 0.0
        self.check_throttle_seconds: float = 1.0
        self._record_mtimes()

    def _should_ignore(self, path: Path) -> bool:
        parts = path.parts
        for ignored in IGNORED_DIRS:
            if "/" in ignored or "\\" in ignored:
                if str(path).replace("\\", "/").find(ignored) != -1:
                    return True
            elif ignored in parts:
                return True
        return False

    def _record_mtimes(self):
        for root in self.watch_roots:
            if not root.exists():
                continue
            for p in root.rglob("*"):
                if self._should_ignore(p):
                    continue
                if p.is_file() and p.suffix in (".py", ".json", ".md"):
                    try:
                        self.file_mtimes[str(p.resolve())] = p.stat().st_mtime
                    except Exception:
                        pass

    def check_for_changes(self) -> List[str]:
        """Checks if any watched source files have been modified or added with throttling."""
        now = time.time()
        if now - self.last_check_time < self.check_throttle_seconds:
            return []
        self.last_check_time = now

        changed_files = []
        current_files: Set[str] = set()

        for root in self.watch_roots:
            if not root.exists():
                continue
            for p in root.rglob("*"):
                if self._should_ignore(p):
                    continue
                if p.is_file() and p.suffix in (".py", ".json", ".md"):
                    p_str = str(p.resolve())
                    current_files.add(p_str)
                    try:
                        mtime = p.stat().st_mtime
                        if p_str not in self.file_mtimes:
                            self.file_mtimes[p_str] = mtime
                            changed_files.append(p.name)
                        elif self.file_mtimes[p_str] != mtime:
                            self.file_mtimes[p_str] = mtime
                            changed_files.append(p.name)
                    except Exception:
                        pass

        # Check deleted files
        deleted = set(self.file_mtimes.keys()) - current_files
        for d in deleted:
            del self.file_mtimes[d]
            changed_files.append(Path(d).name)

        return list(set(changed_files))

    def reload(self, changed_files: Optional[List[str]] = None) -> bool:
        """Reloads all Python modules and refreshes the Kratos runtime."""
        try:
            for mod_name in MODULES_IN_ORDER:
                if mod_name in sys.modules:
                    try:
                        importlib.reload(sys.modules[mod_name])
                    except Exception:
                        pass

            # Refresh runtime instance
            main_mod = sys.modules.get("kratos_agent.main")
            if main_mod and hasattr(main_mod, "runtime"):
                main_mod.runtime.reload_tools()

            return True
        except Exception as e:
            console.print(f"[bold red]❌ Hot-reload error:[/bold red] {e}")
            return False

    def auto_reload_if_changed(self) -> bool:
        """Checks for changes and triggers reload if needed. Returns True if reloaded."""
        changed = self.check_for_changes()
        if changed:
            success = self.reload(changed)
            if success:
                files_preview = ", ".join(changed[:4])
                if len(changed) > 4:
                    files_preview += f" (+{len(changed)-4} more)"
                console.print(f"[bold yellow]⚡ [Live Code Reload][/bold yellow] [dim]Detected changes in: {files_preview}. Runtime updated.[/dim]\n")
            return success
        return False

# Global reloader instance
code_reloader = CodeReloader()

