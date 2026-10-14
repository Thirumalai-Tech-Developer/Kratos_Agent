import os
import subprocess
import sys

import pytest


def test_studio_import_opens_without_browser_login(tmp_path):
    env = {**os.environ, "LOCALAPPDATA": str(tmp_path), "KRATOS_MODEL_PROVIDER": "chatgpt-web"}
    result = subprocess.run(
        [sys.executable, "-c", "import kratos_agent.product; import kratos_agent.core.model_selection"],
        env=env, capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "KratosAgent/auth").exists(), "Import started a browser connection"


def test_missing_browser_login_is_a_catalog_status_not_startup_exception(monkeypatch):
    from kratos_agent.brain import config
    from kratos_agent.brain.chatgpt_web import chatgpt_web_accounts

    monkeypatch.setenv("KRATOS_MODEL_PROVIDER", "chatgpt-web")
    monkeypatch.setattr(chatgpt_web_accounts, "models", lambda **_: (_ for _ in ()).throw(config.BrainError("Connect the browser")))
    assert config.get_model_catalog() == []
    with pytest.raises(config.ModelCatalogUnavailable, match="Connect the browser"):
        config.get_model_catalog(strict=True)
