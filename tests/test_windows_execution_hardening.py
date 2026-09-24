import inspect
import sys

from kratos_agent.core.agent_loop import AgentLoop
from kratos_agent.core.command_lint import lint_command
from kratos_agent.system.shell.base import ShellInfo
from kratos_agent.system.shell.renderer import render_command_argv
from kratos_agent.utils import tools
from kratos_agent.utils.shell_quote import argv_for


def _windows_powershell():
    return ShellInfo(
        name="powershell",
        version="5.1",
        platform="windows",
        executable="powershell.exe",
        supports_and_operator=False,
        supports_or_operator=False,
    )


def test_nested_cmd_stays_outside_powershell():
    command = "cmd /c echo hello > out.txt"
    assert argv_for("powershell", command)[0] == "cmd.exe"
    argv = render_command_argv(command, _windows_powershell())
    assert argv[0] == "cmd.exe"
    assert argv[-1] == "echo hello > out.txt"


def test_clean_command_repairs_common_url_typo():
    assert tools.clean_command('Invoke-WebRequest -Uri "https//example.com"') == 'Invoke-WebRequest -Uri "https://example.com"'


def test_lint_detects_malformed_url():
    result = lint_command('Invoke-WebRequest -Uri "https//example.com"', "powershell")
    assert not result.ok
    assert any("malformed URL scheme" in problem for problem in result.problems)


def test_missing_powershell_script_is_preflighted(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.chdir(tmp_path)
    missing = tools._missing_script_target("powershell -File build.ps1")
    assert missing == str(tmp_path / "build.ps1")


def test_agent_loop_is_unbounded_by_default():
    default = inspect.signature(AgentLoop.run).parameters["max_steps"].default
    assert default is None
