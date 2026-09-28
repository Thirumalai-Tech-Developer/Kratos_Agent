"""Kratos Harness kernel: plugin container, service hub, and event bus."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .plugin import HarnessPlugin, PluginState

if TYPE_CHECKING:
    from kratos_agent.main import KratosRuntime

    from .presets import HarnessPreset

logger = logging.getLogger(__name__)


class HarnessKernel:
    """The central runtime kernel coordinating plugins, services, presets, and events."""

    def __init__(self, runtime: KratosRuntime | None = None):
        self.runtime: KratosRuntime | None = runtime
        self._plugins: dict[str, HarnessPlugin] = {}
        self._services: dict[str, Any] = {}
        self._event_handlers: dict[str, list[Callable[..., Any]]] = {}
        self.active_preset_name: str = "standard"
        self._preset_directives: list[str] = []
        self._active_tools_filter: set[str] | None = None

    # --------------------------------------------------------------------------
    # Service Registry
    # --------------------------------------------------------------------------

    def register_service(self, name: str, service: Any) -> None:
        """Register a shared service accessible to all plugins."""
        self._services[name] = service
        logger.debug(f"[HarnessKernel] Registered service '{name}'.")

    def unregister_service(self, name: str) -> None:
        """Remove a service from the registry."""
        self._services.pop(name, None)

    def get_service(self, name: str) -> Any | None:
        """Retrieve a registered service by name."""
        return self._services.get(name)

    # --------------------------------------------------------------------------
    # Event Bus
    # --------------------------------------------------------------------------

    def on(self, event: str, handler: Callable[..., Any]) -> Callable[[], None]:
        """Subscribe a handler to a kernel event. Returns a disposable unsubscribe function."""
        if event not in self._event_handlers:
            self._event_handlers[event] = []
        self._event_handlers[event].append(handler)

        def unsubscribe():
            self.off(event, handler)

        return unsubscribe

    def off(self, event: str, handler: Callable[..., Any]) -> None:
        """Unsubscribe a handler from an event."""
        if event in self._event_handlers and handler in self._event_handlers[event]:
            self._event_handlers[event].remove(handler)

    def emit(self, event: str, **kwargs: Any) -> None:
        """Publish an event across all subscribed plugin listeners."""
        handlers = list(self._event_handlers.get(event, []))
        for handler in handlers:
            try:
                handler(**kwargs)
            except Exception as e:
                logger.error(f"[HarnessKernel] Handler error on event '{event}': {e}", exc_info=True)

    # --------------------------------------------------------------------------
    # Plugin Management & Lifecycle
    # --------------------------------------------------------------------------

    def register_plugin(self, plugin: HarnessPlugin, enable_immediately: bool = True) -> bool:
        """Register and optionally start a plugin."""
        name = plugin.name
        if name in self._plugins:
            logger.warning(f"[HarnessKernel] Plugin '{name}' is already registered. Updating registration.")
            self.unregister_plugin(name)

        self._plugins[name] = plugin
        try:
            plugin.on_load(self)
        except Exception as e:
            plugin.state = PluginState.FAILED
            plugin.error_message = str(e)
            logger.error(f"[HarnessKernel] Failed to load plugin '{name}': {e}", exc_info=True)
            try:
                plugin.on_error(e)
            except Exception as err:
                logger.debug(f"[HarnessKernel] Error in on_error for plugin '{name}': {err}")
            return False

        if enable_immediately:
            return self.start_plugin(name)
        return True

    def unregister_plugin(self, name: str) -> bool:
        """Disable and unregister a plugin."""
        plugin = self._plugins.get(name)
        if not plugin:
            return False

        try:
            self.stop_plugin(name)
            plugin.on_unload()
        except Exception as e:
            logger.warning(f"[HarnessKernel] Exception while unloading plugin '{name}': {e}")
        finally:
            self._plugins.pop(name, None)
        return True

    def start_plugin(self, name: str) -> bool:
        """Safely start an individual plugin, validating services and isolating any crash."""
        plugin = self._plugins.get(name)
        if not plugin:
            logger.error(f"[HarnessKernel] Cannot start unknown plugin '{name}'.")
            return False

        # 1. Validate required services
        missing_services = [s for s in plugin.required_services if s not in self._services]
        if missing_services:
            err_msg = f"Missing required services: {', '.join(missing_services)}"
            plugin.state = PluginState.FAILED
            plugin.error_message = err_msg
            logger.error(f"[HarnessKernel] Cannot start plugin '{name}': {err_msg}")
            try:
                plugin.on_error(RuntimeError(err_msg))
            except Exception as err:
                logger.debug(f"[HarnessKernel] Error in on_error for plugin '{name}': {err}")
            return False

        # 2. Validate plugin dependencies
        for dep in plugin.metadata.dependencies:
            dep_plugin = self._plugins.get(dep)
            if not dep_plugin or dep_plugin.state != PluginState.ENABLED:
                err_msg = f"Missing or disabled dependency: '{dep}'"
                plugin.state = PluginState.FAILED
                plugin.error_message = err_msg
                logger.warning(f"[HarnessKernel] Cannot start plugin '{name}': {err_msg}")
                try:
                    plugin.on_error(RuntimeError(err_msg))
                except Exception as err:
                    logger.debug(f"[HarnessKernel] Error in on_error for plugin '{name}': {err}")
                return False

        # 3. Start plugin with try/except isolation
        try:
            plugin.on_start()
            plugin.on_enable()
            plugin.state = PluginState.ENABLED
            plugin.error_message = None

            # Register services provided by this plugin
            for svc in plugin.provides_services:
                if svc not in self._services:
                    self.register_service(svc, plugin)

            self.emit("plugin_enabled", plugin=name)
            logger.debug(f"[HarnessKernel] Plugin '{name}' started successfully.")
            return True
        except Exception as e:
            plugin.state = PluginState.FAILED
            plugin.error_message = str(e)
            logger.error(f"[HarnessKernel] Plugin '{name}' crashed in on_start(): {e}", exc_info=True)
            try:
                plugin.on_error(e)
            except Exception as err:
                logger.debug(f"[HarnessKernel] Error in on_error for plugin '{name}': {err}")
            return False

    def stop_plugin(self, name: str) -> bool:
        """Stop an active plugin and unregister its provided services."""
        plugin = self._plugins.get(name)
        if not plugin or plugin.state != PluginState.ENABLED:
            return False

        # Check if other enabled plugins depend on this plugin
        for other_name, other_plugin in self._plugins.items():
            if other_plugin.state == PluginState.ENABLED and name in other_plugin.metadata.dependencies:
                logger.warning(
                    f"[HarnessKernel] Stopping '{name}' also requires stopping dependent '{other_name}'."
                )
                self.stop_plugin(other_name)

        try:
            plugin.on_stop()
            plugin.on_disable()
            plugin.state = PluginState.DISABLED

            # Unregister services provided by this plugin
            for svc in plugin.provides_services:
                if self._services.get(svc) is plugin:
                    self.unregister_service(svc)

            self.emit("plugin_disabled", plugin=name)
            logger.debug(f"[HarnessKernel] Plugin '{name}' stopped.")
            return True
        except Exception as e:
            plugin.state = PluginState.FAILED
            plugin.error_message = str(e)
            logger.error(f"[HarnessKernel] Failed to stop plugin '{name}': {e}", exc_info=True)
            try:
                plugin.on_error(e)
            except Exception as err:
                logger.debug(f"[HarnessKernel] Error in on_error for plugin '{name}': {err}")
            return False

    def enable_plugin(self, name: str) -> bool:
        """Alias for start_plugin."""
        return self.start_plugin(name)

    def disable_plugin(self, name: str) -> bool:
        """Alias for stop_plugin."""
        return self.stop_plugin(name)

    def get_plugin(self, name: str) -> HarnessPlugin | None:
        """Get plugin instance by name."""
        return self._plugins.get(name)

    def list_plugins(self) -> list[dict[str, Any]]:
        """Return status information for all registered plugins."""
        return [p.get_status() for p in self._plugins.values()]

    # --------------------------------------------------------------------------
    # Preset Application
    # --------------------------------------------------------------------------

    def apply_preset(self, preset_or_name: str | HarnessPreset) -> dict[str, Any]:
        """Apply a harness preset (standard, code, minimal, creator)."""
        from .presets import get_preset

        if isinstance(preset_or_name, str):
            preset = get_preset(preset_or_name)
            if not preset:
                raise ValueError(f"Unknown harness preset: '{preset_or_name}'")
        else:
            preset = preset_or_name

        self.active_preset_name = preset.name
        self._preset_directives = preset.directives
        self._active_tools_filter = set(preset.allowed_tools) if preset.allowed_tools is not None else None

        from .presets import get_plugins_for_preset

        manifest_plugins = get_plugins_for_preset(preset.name)
        enabled_target = (
            set(preset.enabled_plugins)
            if preset.enabled_plugins is not None
            else (set(manifest_plugins) if manifest_plugins else None)
        )

        # Apply preset configuration across all plugins
        for name, plugin in self._plugins.items():
            plugin_cfg = preset.plugin_configs.get(name, {})
            # Enable/disable plugins declared in preset or manifest
            if enabled_target is not None:
                if name in enabled_target and plugin.state != PluginState.ENABLED:
                    self.start_plugin(name)
                elif name not in enabled_target and plugin.state == PluginState.ENABLED:
                    self.stop_plugin(name)

            plugin.apply_preset(preset.name, plugin_cfg)

        self.emit("preset_applied", preset=preset.name, config=preset.to_dict())
        logger.info(f"[HarnessKernel] Applied preset '{preset.name}'.")
        return preset.to_dict()

    def get_allowed_tools(self) -> set[str] | None:
        """Return the allowed tool names under current preset, or None for unrestricted."""
        return self._active_tools_filter

    def get_system_directives(self) -> list[str]:
        """Return additional system prompt directives enforced by the active preset."""
        return list(self._preset_directives)

    def get_status(self) -> dict[str, Any]:
        """Return comprehensive kernel status."""
        return {
            "active_preset": self.active_preset_name,
            "plugins_count": len(self._plugins),
            "enabled_plugins": [
                name for name, p in self._plugins.items() if p.state == PluginState.ENABLED
            ],
            "services": list(self._services.keys()),
            "allowed_tools_count": len(self._active_tools_filter) if self._active_tools_filter is not None else "all",
            "plugins": self.list_plugins(),
        }
