"""Regressions for the Windows CLI failures captured on September 30."""
import base64
import subprocess
import sys
from unittest.mock import patch

import pytest

from kratos_agent.core.command_lint import lint_command
from kratos_agent.core.risk_policy import assess_tool_risk
from kratos_agent.core.runtime_contracts import ToolPermission, ToolSpec
from kratos_agent.system.shell.base import ShellInfo
from kratos_agent.system.shell.renderer import render_command_argv
from kratos_agent.utils.tools import clean_file_path, write_file


@pytest.mark.parametrize("path", [
    "research.js", "file.txt", "build.py", "scratch/nested/research.js",
    "C:/Users/thiru/work/scratch/nested/research.js", "/tmp/scratch/research.js",
    "//server/share/report.md",
])
def test_file_paths_keep_requested_destination(path):
    assert clean_file_path(path) == path


def test_absolute_scratch_write_exists_at_tracked_path(tmp_path):
    target = tmp_path / "scratch" / "nested" / "research.js"
    with patch("kratos_agent.utils.tools.approval_gate.check_write", return_value=True):
        result = write_file(str(target), "console.log('ok');")
    assert "Successfully created" in result
    assert target.read_text(encoding="utf-8") == "console.log('ok');"


def test_date_format_is_read_only_but_disk_format_is_blocked():
    spec = ToolSpec(name="run_terminal_command", description="shell", parameters={}, permission=ToolPermission.EXECUTE)
    assert assess_tool_risk(spec, {"command": 'Get-Date -Format "yyyy-MM-dd"'}, "Check the date") is None
    decision = assess_tool_risk(spec, {"command": "format C:"}, "Check the date")
    assert decision is not None and not decision.authorized


def test_nested_powershell_does_not_expand_variables_in_parent():
    shell = ShellInfo("powershell", "5.1", "windows", "powershell.exe", False, False)
    command = 'powershell -NoProfile -Command "$p = 42; Write-Output $p"'
    argv = render_command_argv(command, shell)
    payload = base64.b64decode(argv[-1]).decode("utf-16-le")
    assert "$p = 42; Write-Output $p" in payload
    assert "-Command" not in payload
    if sys.platform == "win32":
        result = subprocess.run(argv, capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "42"


def test_backslash_quote_error_gives_actionable_hint():
    result = lint_command(r'powershell -Command "node -e \"console.log(1)\""')
    assert not result.ok
    assert "argv" in result.hint


def test_missing_lazy_tokenizer_dependency_uses_estimates():
    pytest.importorskip("headroom")
    from headroom.tokenizers.registry import TokenizerRegistry
    from headroom.tokenizers.estimator import EstimatingTokenCounter
    from kratos_agent.core.harness.plugins.headroom_plugin import prepare_headroom_tokenizer
    from unittest.mock import MagicMock

    counter = MagicMock()
    counter.count_text.side_effect = ModuleNotFoundError("No module named 'transformers'")
    prepare_headroom_tokenizer.cache_clear()
    with patch.object(TokenizerRegistry, "get", return_value=counter), patch.object(TokenizerRegistry, "register") as register:
        prepare_headroom_tokenizer("test/model")
        prepare_headroom_tokenizer("test/model")
    register.assert_called_once()
    assert isinstance(register.call_args.kwargs["tokenizer"], EstimatingTokenCounter)


def test_compression_with_gateway_model_without_ml_dependencies():
    pytest.importorskip("headroom")
    from kratos_agent.core.harness.plugins.headroom_plugin import HeadroomPlugin
    plugin = HeadroomPlugin()
    plugin.on_enable()
    messages = [{"role": "system", "content": "Keep these instructions intact."},
                {"role": "tool", "content": "sample line\n" * 2000}]
    output, stats = plugin.compress_messages(messages, model="ds-web/deepseek-v4-pro")
    assert stats["input_tokens"] > 0
    assert output[0] == messages[0]
