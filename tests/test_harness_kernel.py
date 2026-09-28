"""Tests for DeepSeek HarnessKernel and HarnessPlugin lifecycle isolation."""

import unittest
from typing import Any

from kratos_agent.core.harness.kernel import HarnessKernel
from kratos_agent.core.harness.plugin import HarnessPlugin, PluginMetadata, PluginState
from kratos_agent.core.harness.presets import (
    CodePreset,
    MinimalPreset,
    StandardPreset,
    get_plugins_for_preset,
    load_manifest,
)


class HealthyPlugin(HarnessPlugin):
    """A healthy plugin that succeeds on all lifecycle steps."""

    def __init__(self, name: str = "healthy", provides: list[str] | None = None, req: list[str] | None = None):
        super().__init__(
            metadata=PluginMetadata(
                name=name,
                version="1.0.0",
                description="Healthy test plugin",
                provides_services=provides or [f"{name}_service"],
                required_services=req or [],
            )
        )
        self.registered = False
        self.started = False
        self.stopped = False
        self.errors: list[Exception] = []

    def on_register(self) -> None:
        self.registered = True

    def on_start(self) -> None:
        self.started = True

    def on_stop(self) -> None:
        self.stopped = True

    def on_error(self, exc: Exception) -> None:
        self.errors.append(exc)


class CrashingPlugin(HarnessPlugin):
    """A plugin that intentionally raises in on_start()."""

    def __init__(self, name: str = "crashing"):
        super().__init__(
            metadata=PluginMetadata(
                name=name,
                version="1.0.0",
                description="Crashing test plugin",
                provides_services=["crash_service"],
            )
        )
        self.error_received = None

    def on_start(self) -> None:
        raise RuntimeError("Simulated startup failure in CrashingPlugin!")

    def on_error(self, exc: Exception) -> None:
        self.error_received = exc


class TestHarnessKernel(unittest.TestCase):
    """Unit tests for HarnessKernel plugin isolation and lifecycle contracts."""

    def setUp(self):
        self.kernel = HarnessKernel()

    def test_plugin_crashing_in_on_start_does_not_crash_kernel(self):
        """A plugin that throws in on_start() is marked FAILED and does not crash kernel."""
        crashing = CrashingPlugin()
        healthy = HealthyPlugin(name="healthy_companion")

        # Register both plugins
        success_crash = self.kernel.register_plugin(crashing, enable_immediately=True)
        success_healthy = self.kernel.register_plugin(healthy, enable_immediately=True)

        self.assertFalse(success_crash)
        self.assertTrue(success_healthy)

        # Crashing plugin state is FAILED and received the error
        self.assertEqual(crashing.state, PluginState.FAILED)
        self.assertIsNotNone(crashing.error_message)
        self.assertIn("Simulated startup failure", crashing.error_message)
        self.assertIsNotNone(crashing.error_received)

        # Healthy plugin is ENABLED and running
        self.assertEqual(healthy.state, PluginState.ENABLED)
        self.assertTrue(healthy.started)

        # Kernel service for healthy plugin is registered, crashing is not
        self.assertIsNotNone(self.kernel.get_service("healthy_companion_service"))
        self.assertIsNone(self.kernel.get_service("crash_service"))

    def test_missing_required_services_fails_loudly(self):
        """A plugin with required_services that are not provided fails to start."""
        plugin = HealthyPlugin(name="needs_db", req=["database_service"])
        success = self.kernel.register_plugin(plugin, enable_immediately=True)

        self.assertFalse(success)
        self.assertEqual(plugin.state, PluginState.FAILED)
        self.assertIn("Missing required services: database_service", plugin.error_message)
        self.assertEqual(len(plugin.errors), 1)

        # Now register the required service and retry starting
        self.kernel.register_service("database_service", {"db": "mock_connection"})
        retry_success = self.kernel.start_plugin("needs_db")

        self.assertTrue(retry_success)
        self.assertEqual(plugin.state, PluginState.ENABLED)

    def test_lifecycle_hooks_called_in_order(self):
        """on_register, on_start, on_stop are called appropriately."""
        plugin = HealthyPlugin(name="lifecycle_tester")
        self.kernel.register_plugin(plugin, enable_immediately=False)

        self.assertTrue(plugin.registered)
        self.assertFalse(plugin.started)
        self.assertEqual(plugin.state, PluginState.LOADED)

        # Start plugin
        self.kernel.start_plugin("lifecycle_tester")
        self.assertTrue(plugin.started)
        self.assertEqual(plugin.state, PluginState.ENABLED)

        # Stop plugin
        self.kernel.stop_plugin("lifecycle_tester")
        self.assertTrue(plugin.stopped)
        self.assertEqual(plugin.state, PluginState.DISABLED)

    def test_manifest_loading_and_presets(self):
        """Manifest loads correctly and preset mappings are accurate."""
        manifest = load_manifest()
        self.assertIn("plugins", manifest)
        plugins = manifest["plugins"]
        self.assertIn("memory", plugins)
        self.assertIn("tools", plugins)
        self.assertIn("audit", plugins)
        self.assertIn("creator", plugins)

        # Minimal preset should contain tools and memory per manifest or preset
        minimal_plugins = get_plugins_for_preset("minimal")
        self.assertIn("tools", minimal_plugins)
        self.assertIn("memory", minimal_plugins)

        # Standard preset should include all core plugins
        std_plugins = get_plugins_for_preset("standard")
        self.assertIn("tools", std_plugins)
        self.assertIn("memory", std_plugins)
        self.assertIn("audit", std_plugins)
        self.assertIn("creator", std_plugins)

    def test_apply_preset_activates_expected_plugins(self):
        """apply_preset enables designated plugins and disables others."""
        p_tools = HealthyPlugin(name="tools")
        p_audit = HealthyPlugin(name="audit")
        p_creator = HealthyPlugin(name="creator")

        self.kernel.register_plugin(p_tools, enable_immediately=True)
        self.kernel.register_plugin(p_audit, enable_immediately=True)
        self.kernel.register_plugin(p_creator, enable_immediately=True)

        self.assertEqual(p_tools.state, PluginState.ENABLED)
        self.assertEqual(p_audit.state, PluginState.ENABLED)
        self.assertEqual(p_creator.state, PluginState.ENABLED)

        # Apply minimal preset (which enables only core tool controls)
        self.kernel.apply_preset("minimal")

        self.assertEqual(p_tools.state, PluginState.ENABLED)
        self.assertEqual(p_audit.state, PluginState.DISABLED)
        self.assertEqual(p_creator.state, PluginState.DISABLED)


if __name__ == "__main__":
    unittest.main()
