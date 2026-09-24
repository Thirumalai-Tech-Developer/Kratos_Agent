import os
import json
from unittest.mock import patch

from kratos_agent.core.approval_mode import ApprovalMode, ApprovalGate


def test_sovereign_resolves_every_capability_tag_without_confirmation(tmp_path):
    settings = tmp_path / "settings.json"
    with patch.object(ApprovalGate, "SETTINGS_FILE", settings), patch.dict(os.environ, {}, clear=True):
        gate = ApprovalGate()
        assert gate.mode is ApprovalMode.SOVEREIGN
        for tag in (
            "read", "write", "execute", "git", "network", "input", "display",
            "gui", "system", "admin", "registry", "install", "destructive",
            "browser", "persist",
        ):
            decision = gate.resolve(tag, "user-test-target")
            assert decision.allow is True
            assert decision.needs_confirmation is False


def test_env_overrides_settings(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"approval_mode": "suggest"}), encoding="utf-8")
    with patch.object(ApprovalGate, "SETTINGS_FILE", settings), patch.dict(os.environ, {"KRATOS_APPROVAL_MODE": "sovereign"}, clear=True):
        gate = ApprovalGate()
        assert gate.mode is ApprovalMode.SOVEREIGN


def test_other_modes_remain_available(tmp_path):
    settings = tmp_path / "settings.json"
    with patch.object(ApprovalGate, "SETTINGS_FILE", settings), patch.dict(os.environ, {"KRATOS_APPROVAL_MODE": "suggest"}, clear=True):
        gate = ApprovalGate()
        assert gate.mode is ApprovalMode.SUGGEST
        decision = gate.resolve("write", "file.txt")
        assert decision.allow is False
        assert decision.needs_confirmation is True
