from pathlib import Path
import importlib.util
import sys
import types

ROOT = Path(__file__).resolve().parents[1]


def _load_lint():
    base = ROOT / "src/kratos_agent"
    kr = types.ModuleType("kratos_agent"); kr.__path__=[str(base)]; sys.modules["kratos_agent"]=kr
    utils = types.ModuleType("kratos_agent.utils"); utils.__path__=[str(base/"utils")]; sys.modules["kratos_agent.utils"]=utils
    sp = importlib.util.spec_from_file_location("kratos_agent.utils.shell_quote", base/"utils/shell_quote.py")
    sm = importlib.util.module_from_spec(sp); sys.modules[sp.name]=sm; sp.loader.exec_module(sm)
    core = types.ModuleType("kratos_agent.core"); core.__path__=[str(base/"core")]; sys.modules["kratos_agent.core"]=core
    sp = importlib.util.spec_from_file_location("kratos_agent.core.command_lint", base/"core/command_lint.py")
    cm = importlib.util.module_from_spec(sp); sys.modules[sp.name]=cm; sp.loader.exec_module(cm)
    return cm.lint_command


def test_long_inline_frontend_source_is_rejected_before_powershell():
    lint_command = _load_lint()
    cmd = 'node -e "const app = {}; ' + ('x' * 320) + ' @keyframes float { 0% { transform: translateY(0); } 100% { transform: translateY(4px); } }"'
    result = lint_command(cmd, "powershell")
    assert result.ok is False
    assert result.code == "SOURCE_AS_COMMAND"
    assert "write_file" in result.suggestion["recommended_tools"]


def test_normal_build_command_still_passes():
    assert _load_lint()("npm run build", "powershell").ok


def test_malformed_url_is_still_rejected():
    result = _load_lint()("Invoke-WebRequest -Uri https//example.com", "powershell")
    assert result.ok is False
    assert any("malformed URL scheme" in p for p in result.problems)
