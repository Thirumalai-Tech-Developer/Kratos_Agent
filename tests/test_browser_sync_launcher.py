from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kratos_agent import product


def test_watcher_uses_workspace_store_and_is_optional(tmp_path, monkeypatch):
    args = MagicMock(workspace=tmp_path)
    monkeypatch.setattr(product.shutil, 'which', lambda name: 'node')
    assert product.browser_sync_service(args, {}) is None
    env = {'KRATOS_BROWSER_SESSION_SYNC': 'true', 'DATA_DIR': str(tmp_path / 'store'),
           'KRATOS_BROWSER_SESSION_PROVIDERS': 'all'}
    watcher = product.browser_sync_service(args, env)
    assert watcher.name == 'Browser session sync'
    assert watcher.command[watcher.command.index('--workspace') + 1] == str(tmp_path.resolve())
    assert watcher.command[watcher.command.index('--providers') + 1] == 'all'
    assert watcher.env is env


def test_manual_watcher_resolves_caller_workspace_before_changing_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(product.shutil, 'which', lambda name: 'node')
    call = MagicMock(return_value=0)
    monkeypatch.setattr(product.subprocess, 'call', call)
    with pytest.raises(SystemExit) as result:
        product.main(['browser-sync', '--workspace', '.', '--list'])
    assert result.value.code == 0
    command = call.call_args.args[0]
    assert command[command.index('--workspace') + 1] == str(tmp_path.resolve())
    assert call.call_args.kwargs['cwd'] == product.GATEWAY
