"""Creator Plugin - Meta-programming engine for authoring, hot-reloading, and inspecting plugins."""

from __future__ import annotations

import ast
import logging
from typing import TYPE_CHECKING, Any

from ..plugin import HarnessPlugin, PluginMetadata

if TYPE_CHECKING:
    from ..kernel import HarnessKernel

logger = logging.getLogger(__name__)


class CreatorPlugin(HarnessPlugin):
    """Meta-programming runtime allowing autonomous authoring, hot-reloading, and inspection of plugins."""

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(
            metadata=PluginMetadata(
                name="creator",
                version="1.0.0",
                description="Meta-programming runtime for authoring and inspecting harness plugins.",
                category="creator",
                required_services=[],
                provides_services=["creator"],
            ),
            config=config,
        )

    def on_register(self) -> None:
        """Called when creator plugin is registered."""
        pass

    def on_start(self) -> None:
        """Called when creator plugin starts."""
        pass

    def on_stop(self) -> None:
        """Called when creator plugin stops."""
        pass

    def on_error(self, exc: Exception) -> None:
        """Called when an error occurs in the creator plugin."""
        super().on_error(exc)

    def on_load(self, kernel: HarnessKernel) -> None:
        super().on_load(kernel)
        kernel.register_service("creator", self)

    def on_unload(self) -> None:
        if self.kernel:
            self.kernel.unregister_service("creator")
        super().on_unload()

    def generate_plugin_scaffold(
        self,
        name: str,
        description: str = "",
        category: str = "general",
        dependencies: list[str] | None = None,
    ) -> str:
        """Generate boilerplate Python code for a new HarnessPlugin."""
        deps = dependencies or []
        class_name = "".join(part.capitalize() for part in name.replace("-", "_").split("_")) + "Plugin"

        return f'''"""Auto-generated Harness Plugin: {name}"""

from typing import Any, Dict, Optional
from kratos_agent.core.harness.plugin import HarnessPlugin, PluginMetadata


class {class_name}(HarnessPlugin):
    """{description or f"{name} plugin"}"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(
            metadata=PluginMetadata(
                name="{name.lower()}",
                version="1.0.0",
                description="{description}",
                category="{category}",
                dependencies={deps!r},
            ),
            config=config,
        )

    def on_load(self, kernel):
        super().on_load(kernel)
        # Register services or event listeners here

    def on_enable(self):
        super().on_enable()
        # Activate plugin functionality

    def on_disable(self):
        super().on_disable()
        # Deactivate and clean up

    def on_unload(self):
        super().on_unload()
        # Final cleanup
'''

    def validate_plugin_code(self, source_code: str) -> tuple[bool, str | None]:
        """Validate Python source code for AST syntax correctness and security policies."""
        try:
            tree = ast.parse(source_code)
            # Verify at least one class definition exists
            classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
            if not classes:
                return False, "Source code does not define any class."

            from kratos_agent.utils.tool_sandbox import validate_tool_ast
            valid, err = validate_tool_ast(source_code, allow_subprocess=False)
            if not valid:
                return False, f"Static analysis security rejection: {err}"

            return True, None
        except SyntaxError as e:
            return False, f"Syntax error at line {e.lineno}: {e.msg}"
        except Exception as e:
            return False, str(e)

    def load_plugin_from_source(
        self,
        source_code: str,
        class_name: str,
        enable: bool = True,
    ) -> tuple[HarnessPlugin | None, str | None]:
        """Dynamically compile and register a plugin from source code into the active kernel."""
        if not self.kernel:
            return None, "Kernel is not attached."

        import os
        if os.environ.get("KRATOS_ALLOW_DYNAMIC_PLUGINS", "false").lower() != "true":
            return None, "Dynamic plugin loading is disabled. Set KRATOS_ALLOW_DYNAMIC_PLUGINS=true to enable."

        valid, err = self.validate_plugin_code(source_code)
        if not valid:
            return None, err

        namespace: dict[str, Any] = {}
        try:
            compiled = compile(source_code, f"<dynamic_plugin_{class_name}>", "exec")
            exec(compiled, namespace)
        except Exception as e:
            return None, f"Failed to compile plugin: {e}"

        plugin_cls = namespace.get(class_name)
        if not plugin_cls or not isinstance(plugin_cls, type) or not issubclass(plugin_cls, HarnessPlugin):
            return None, f"Class '{class_name}' is not a valid HarnessPlugin subclass."

        try:
            plugin_instance = plugin_cls()
            success = self.kernel.register_plugin(plugin_instance, enable_immediately=enable)
            if not success:
                return None, f"Kernel failed to register plugin '{plugin_instance.name}'."
            return plugin_instance, None
        except Exception as e:
            return None, f"Error instantiating plugin: {e}"

    def inspect_system(self) -> dict[str, Any]:
        """Return full introspection of the kernel, presets, and registered services."""
        if not self.kernel:
            return {"error": "No kernel attached."}
        return self.kernel.get_status()
