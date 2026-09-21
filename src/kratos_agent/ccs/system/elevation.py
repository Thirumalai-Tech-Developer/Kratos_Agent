"""
Privilege Elevation System.
Spawns a persistent elevated helper process to execute high-IL inputs,
registry writes, and file operations without repeatedly popping UAC prompts.
"""
import os
import ctypes
import uuid
import subprocess
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class ElevationManager:
    def __init__(self):
        self.session_token = str(uuid.uuid4())
        self.pipe_name = rf"\\.\pipe\kratos_ccs_{self.session_token}"
        self.helper_process = None

    def is_elevated(self) -> bool:
        """Check if the current process is already elevated."""
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() == 1
        except Exception:
            return False

    def spawn_helper(self) -> bool:
        """Spawn the elevated helper process via ShellExecuteW."""
        if self.is_elevated():
            return True
            
        logger.info("Spawning elevated helper process (may trigger UAC).")
        import sys
        
        # Prepare to run elevated_helper.py
        helper_script = os.path.join(os.path.dirname(os.path.dirname(__file__)), "elevated_helper.py")
        
        try:
            # Requires win32com or ctypes ShellExecute
            result = ctypes.windll.shell32.ShellExecuteW(
                None, 
                "runas", 
                sys.executable, 
                f'"{helper_script}" {self.pipe_name} {self.session_token}', 
                None, 
                1
            )
            if result <= 32:
                logger.error(f"Failed to spawn elevated helper. Error code: {result}")
                return False
            return True
        except Exception as e:
            logger.error(f"Elevation prompt failed: {e}")
            return False

    def check_secure_desktop(self) -> bool:
        """Detect if UAC secure desktop is active."""
        try:
            # OpenInputDesktop fails when secure desktop is active
            user32 = ctypes.windll.user32
            hdesk = user32.OpenInputDesktop(0, False, 0x0100)
            if hdesk == 0:
                return True
            user32.CloseDesktop(hdesk)
            return False
        except Exception:
            return False

elevation_manager = ElevationManager()
