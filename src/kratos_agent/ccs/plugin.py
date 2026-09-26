"""
Harness Plugin for Computer Control Subsystem (CCS).
"""

import logging
logger = logging.getLogger(__name__)
from kratos_agent.core.harness.plugins import HarnessPlugin


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
                        except Exception as exc:
                            logger.debug("Operation error suppressed: %s", exc)
