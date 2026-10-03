"""Lifecycle for the installed official WhatsApp routing bridge."""
import os
import shutil
import subprocess
from pathlib import Path

from dotenv import dotenv_values

from ..plugin import HarnessPlugin, PluginMetadata


class WhatsAppPlugin(HarnessPlugin):
    metadata = PluginMetadata(name='whatsapp-official', version='0.1.0',
        description='Official WhatsApp routing bridge with a Kratos session adapter',
        category='communication', tags=['whatsapp', 'meta', '360dialog'])

    def __init__(self, workspace: Path):
        super().__init__()
        self.workspace = workspace
        self.directory = workspace / '.kratos/plugins/whatsapp-official'
        self.process = None
        self.log = None
        self.connection_status = 'not_enabled'

    def on_start(self):
        if self.process is not None:
            return
        config = dotenv_values(self.directory / '.env')
        if str(config.get('WHATSAPP_BRIDGE_ENABLED', '')).lower() != 'true':
            return
        required = ['ROUTING_BASE_URL', 'ROUTING_API_KEY', 'WHATSAPP_ALLOWED_PHONES']
        if any(not config.get(name) for name in required) or not os.getenv('KRATOS_INTERNAL_TOKEN'):
            self.connection_status = 'needs_configuration'
            return
        node = shutil.which('node')
        if not node:
            self.connection_status = 'node_unavailable'
            return
        env = dict(os.environ)
        # Plugin configuration cannot override Studio's internal authentication.
        for name in ['ROUTING_BASE_URL', 'ROUTING_API_KEY', 'WHATSAPP_ALLOWED_PHONES', 'WHATSAPP_AGENT_MODE']:
            if config.get(name) is not None:
                env[name] = config[name]
        self.log = (self.directory / 'bridge.log').open('a', encoding='utf-8')
        self.process = subprocess.Popen([node, '--experimental-strip-types', str(self.workspace / 'plugins/whatsapp-official/bridge.mjs')],
            cwd=self.workspace, env=env, stdin=subprocess.PIPE, stdout=self.log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.connection_status = 'starting'

    def on_stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process = None
        if self.log:
            self.log.close()
            self.log = None
        self.connection_status = 'stopped'

    def get_status(self):
        status = super().get_status()
        connection = self.connection_status
        if self.process is not None:
            connection = 'running' if self.process.poll() is None else 'exited'
        status.update(connection_status=connection, configuration_file=str(self.directory / '.env'))
        return status
