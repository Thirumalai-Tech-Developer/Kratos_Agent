"""DeepSeek Harness Kernel - Plugin container, service hub, and event bus."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set, Union

from .plugin import HarnessPlugin, PluginState

if TYPE_CHECKING:
    from .presets import HarnessPreset
    from kratos_agent.main import KratosRuntime

logger = logging.getLogger(__name__)


class HarnessKernel:
    """The central runtime kernel coordinating plugins, services, presets, and events."""

    def __init__(self, runtime: Optional["KratosRuntime"] = None):
        self.runtime: Optional["KratosRuntime"] = runtime
        self._plugins: Dict[str, HarnessPlugin] = {}
        self._services: Dict[str, Any] = {}
        self._event_handlers: Dict[str, List[Callable[..., Any]]] = {}
        self.active_preset_name: str = "standard"
        self._preset_directives: List[str] = []
        self._active_tools_filter: Optional[Set[str]] = None

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

    def get_service(self, name: str) -> Optional[Any]:
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
        """Register and optionally enable a plugin."""
        name = plugin.name
        if name in self._plugins:
            logger.warning(f"[HarnessKernel] Plugin '{name}' is already registered. Updating registration.")
            self.unregister_plugin(name)

        self._plugins[name] = plugin
        try:
            plugin.on_load(self)
        except Exception as e:
            plugin.state = PluginState.ERROR
            plugin.error_message = str(e)
            logger.error(f"[HarnessKernel] Failed to load plugin '{name}': {e}", exc_info=True)
            return False

        if enable_immediately:
            return self.enable_plugin(name)
        return True

    def unregister_plugin(self, name: str) -> bool:
        """Disable and unregister a plugin."""
        plugin = self._plugins.get(name)
        if not plugin:
            return False

        try:
            plugin.on_unload()
        except Exception as e:
            logger.warning(f"[HarnessKernel] Exception while unloading plugin '{name}': {e}")
        finally:
            self._plugins.pop(name, None)
        return True

    def enable_plugin(self, name: str) -> bool:
        """Enable a loaded plugin after verifying its dependencies."""
        plugin = self._plugins.get(name)
        if not plugin:
            logger.error(f"[HarnessKernel] Cannot enable unknown plugin '{name}'.")
            return False

        # Validate dependencies
        for dep in plugin.metadata.dependencies:
            dep_plugin = self._plugins.get(dep)
            if not dep_plugin or dep_plugin.state != PluginState.ENABLED:
                logger.warning(
                    f"[HarnessKernel] Cannot enable '{name}': missing or disabled dependency '{dep}'."
                )
                return False

        try:
            plugin.on_enable()
            self.emit("plugin_enabled", plugin=name)
            return True
        except Exception as e:
            plugin.state = PluginState.ERROR
            plugin.error_message = str(e)
            logger.error(f"[HarnessKernel] Failed to enable plugin '{name}': {e}", exc_info=True)
            return False

    def disable_plugin(self, name: str) -> bool:
        """Disable an active plugin."""
        plugin = self._plugins.get(name)
        if not plugin or plugin.state != PluginState.ENABLED:
            return False

        # Check if other enabled plugins depend on this plugin
        for other_name, other_plugin in self._plugins.items():
            if other_plugin.state == PluginState.ENABLED and name in other_plugin.metadata.dependencies:
                logger.warning(
                    f"[HarnessKernel] Disabling '{name}' also requires disabling dependent '{other_name}'."
                )
                self.disable_plugin(other_name)

        try:
            plugin.on_disable()
            self.emit("plugin_disabled", plugin=name)
            return True
        except Exception as e:
            plugin.state = PluginState.ERROR
            plugin.error_message = str(e)
            logger.error(f"[HarnessKernel] Failed to disable plugin '{name}': {e}", exc_info=True)
            return False

    def get_plugin(self, name: str) -> Optional[HarnessPlugin]:
        """Get plugin instance by name."""
        return self._plugins.get(name)

    def list_plugins(self) -> List[Dict[str, Any]]:
        """Return status information for all registered plugins."""
        return [p.get_status() for p in self._plugins.values()]

    # --------------------------------------------------------------------------
    # Preset Application
    # --------------------------------------------------------------------------

    def apply_preset(self, preset_or_name: Union[str, "HarnessPreset"]) -> Dict[str, Any]:
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

        # Apply preset configuration across all plugins
        for name, plugin in self._plugins.items():
            plugin_cfg = preset.plugin_configs.get(name, {})
            # Enable/disable plugins declared in preset
            if preset.enabled_plugins is not None:
                if name in preset.enabled_plugins and plugin.state != PluginState.ENABLED:
                    self.enable_plugin(name)
                elif name not in preset.enabled_plugins and plugin.state == PluginState.ENABLED:
                    self.disable_plugin(name)

            plugin.apply_preset(preset.name, plugin_cfg)

        self.emit("preset_applied", preset=preset.name, config=preset.to_dict())
        logger.info(f"[HarnessKernel] Applied preset '{preset.name}'.")
        return preset.to_dict()

    def get_allowed_tools(self) -> Optional[Set[str]]:
        """Return the allowed tool names under current preset, or None for unrestricted."""
        return self._active_tools_filter

    def get_system_directives(self) -> List[str]:
        """Return additional system prompt directives enforced by the active preset."""
        return list(self._preset_directives)

    def get_status(self) -> Dict[str, Any]:
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
