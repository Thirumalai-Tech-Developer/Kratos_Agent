from unittest.mock import patch

from kratos_agent.core.harness.plugins.whatsapp_plugin import WhatsAppPlugin
from kratos_agent.core.harness.kernel import HarnessKernel


def test_installed_plugin_is_visible_without_starting_a_live_bridge(tmp_path):
    directory = tmp_path / '.kratos/plugins/whatsapp-official'
    directory.mkdir(parents=True)
    (directory / '.env').write_text('WHATSAPP_BRIDGE_ENABLED=false\n')
    plugin = WhatsAppPlugin(tmp_path)
    kernel = HarnessKernel()
    with patch('subprocess.Popen') as popen:
        assert kernel.register_plugin(plugin)
        assert plugin.get_status()['connection_status'] == 'not_enabled'
        popen.assert_not_called()


def test_missing_credentials_do_not_start_a_bridge(tmp_path, monkeypatch):
    directory = tmp_path / '.kratos/plugins/whatsapp-official'
    directory.mkdir(parents=True)
    (directory / '.env').write_text('WHATSAPP_BRIDGE_ENABLED=true\n')
    monkeypatch.delenv('KRATOS_INTERNAL_TOKEN', raising=False)
    plugin = WhatsAppPlugin(tmp_path)
    with patch('subprocess.Popen') as popen:
        plugin.on_start()
        assert plugin.get_status()['connection_status'] == 'needs_configuration'
        popen.assert_not_called()
