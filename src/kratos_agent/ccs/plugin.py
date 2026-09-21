"""
Harness Plugin for Computer Control Subsystem (CCS).
"""
from kratos_agent.core.harness.plugins import HarnessPlugin
from kratos_agent.core.runtime_contracts import ToolSpec, ToolPermission

class CCSHarnessPlugin(HarnessPlugin):
    @property
    def name(self) -> str:
        return "ccs"
        
    def on_register(self, harness) -> None:
        """Register CCS tools into the runtime."""
        if hasattr(harness, "register_tool"):
            from kratos_agent.utils import computer_tools
            for fn_name in dir(computer_tools):
                if fn_name.startswith("gui_") or fn_name in ("system_inspect", "window_manager", "application_manager"):
                    fn = getattr(computer_tools, fn_name)
                    if callable(fn):
                        try:
                            harness.register_tool(fn_name, fn)
                        except Exception:
                            pass
