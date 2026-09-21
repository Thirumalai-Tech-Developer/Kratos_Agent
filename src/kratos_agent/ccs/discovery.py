import platform
import os
from typing import Dict, Any, Optional

from .base import ComputerController

_CONTROLLER_INSTANCE: Optional[ComputerController] = None
_CAPABILITY_MAP: Optional[Dict[str, Any]] = None

def get_computer_controller() -> ComputerController:
    """Returns the platform-specific computer controller singleton."""
    global _CONTROLLER_INSTANCE
    if _CONTROLLER_INSTANCE is not None:
        return _CONTROLLER_INSTANCE
        
    system = platform.system().lower()
    
    if system == "windows":
        from .windows import WindowsComputerController
        _CONTROLLER_INSTANCE = WindowsComputerController()
    elif system == "linux":
        from .linux import LinuxComputerController
        _CONTROLLER_INSTANCE = LinuxComputerController()
    else:
        from .base import CapabilityUnavailable
        raise CapabilityUnavailable(
            capability="computer_control",
            platform=system,
            hint=f"Computer control not supported on OS: {system}",
        )
        
    return _CONTROLLER_INSTANCE

def get_capability_map() -> Dict[str, Any]:
    """Detects and caches the host's capabilities."""
    global _CAPABILITY_MAP
    if _CAPABILITY_MAP is not None:
        return _CAPABILITY_MAP
        
    system = platform.system()
    controller = None
    gui_available = False
    
    try:
        controller = get_computer_controller()
        gui_available = True
    except Exception:
        gui_available = False

    is_admin = False
    if system.lower() == "windows":
        import ctypes
        try:
            is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            is_admin = False
    else:
        is_admin = os.geteuid() == 0

    _CAPABILITY_MAP = {
        "os": system,
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "admin": is_admin,
        "gui": gui_available,
        "keyboard": gui_available,
        "mouse": gui_available,
        "screen": gui_available,
        "network": True,
        # Default to True, specific tests can determine more accurately later
        "browser": True, 
        "audio": True,
        "microphone": True,
        "camera": True
    }
    
    return _CAPABILITY_MAP
