"""
Safety Operations Subsystem for Sovereign mode.
Handles emergency panic (Ctrl+Alt+Shift+F12), snapshots, and audit logging.
"""
import hashlib
import json
import logging
import os
import re
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

class Redactor:
    """Redacts sensitive information from audit logs."""
    SECRET_PATTERN = re.compile(
        r"(?i)(api[_-]?key|token|password|secret|bearer|authorization|cookie|private[_-]?key).*?['\"]?([a-zA-Z0-9_\-\.]{20,})['\"]?"
    )

    @classmethod
    def redact(cls, text: str) -> str:
        if not text: return text
        return cls.SECRET_PATTERN.sub(r"\1=«REDACTED:sha8»", text)

    @classmethod
    def redact_dict(cls, data: dict) -> dict:
        redacted = {}
        for k, v in data.items():
            if isinstance(v, str):
                redacted[k] = cls.redact(v)
            elif isinstance(v, dict):
                redacted[k] = cls.redact_dict(v)
            else:
                redacted[k] = v
        return redacted

class SnapshotEngine:
    def __init__(self):
        self.snapshot_dir = Path(".kratos/snapshots")
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        
    def create_snapshot(self, task_id: str, file_path: Path) -> str:
        """Create a pre-image snapshot of a file."""
        if not file_path.exists(): return ""
        try:
            content = file_path.read_bytes()
            sha256 = hashlib.sha256(content).hexdigest()
            task_dir = self.snapshot_dir / task_id
            task_dir.mkdir(parents=True, exist_ok=True)
            snapshot_path = task_dir / f"{sha256}{file_path.suffix}"
            if not snapshot_path.exists():
                snapshot_path.write_bytes(content)
            return str(snapshot_path)
        except Exception as e:
            logger.error(f"Snapshot failed: {e}")
            return ""

    def restore_snapshot(self, snapshot_path: str, target_path: str) -> bool:
        try:
            shutil.copy2(snapshot_path, target_path)
            return True
        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return False

snapshot_engine = SnapshotEngine()

class SafetyOps:
    def __init__(self):
        self.audit_log = Path(".kratos/audit")
        self.audit_log.mkdir(parents=True, exist_ok=True)
        
    def panic(self):
        """Emergency stop. Halt all agent actions."""
        logger.warning("EMERGENCY PANIC TRIGGERED!")
        os._exit(1) # Hard exit
        
    def record_audit(self, capability: str, target: str | None, decision: str, mode: str, args: dict = None):
        """Append to the sovereign audit trail."""
        import datetime
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")
        log_file = self.audit_log / f"{date_str}.jsonl"
        timestamp = datetime.datetime.now().isoformat()
        
        redacted_args = Redactor.redact_dict(args) if args else {}
        
        record = {
            "ts": timestamp,
            "capability": capability,
            "target": target,
            "decision": decision,
            "mode": mode,
            "args_redacted": redacted_args
        }
        
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            logger.error(f"Audit log failure: {e}")

safety = SafetyOps()

def undo_last_operation(task_id: str, snapshot_path: str, target_path: str) -> str:
    """Tool to reverse changes by rolling back snapshots."""
    success = snapshot_engine.restore_snapshot(snapshot_path, target_path)
    if success:
        return f"Successfully restored {target_path} from snapshot."
    return f"Failed to restore {target_path}."

def panic_halt(reason: str = "emergency_panic") -> None:
    """Emergency halt releasing all keys/mouse and recording an audit trace."""
    logger.warning("EMERGENCY PANIC HALT TRIGGERED: %s", reason)
    try:
        from kratos_agent.ccs.discovery import get_computer_controller
        ctrl = get_computer_controller()
        ctrl.input_release_all()
    except Exception as exc:
        logger.debug("Operation error suppressed: %s", exc)
    safety.record_audit(capability="panic_halt", target=None, decision="halt", mode="sovereign", args={"reason": reason})

