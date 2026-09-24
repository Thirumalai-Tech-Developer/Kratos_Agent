"""Computer actions must use semantic controls or keyboard input, never XY input."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from kratos_agent.computer.executor import ActionExecutor
from kratos_agent.computer.gui.backends.coordinate import CoordinateBackend
from kratos_agent.computer.gui.backends.windows_uia import WindowsUIABackend
from kratos_agent.computer.gui.models import GUIElement
from kratos_agent.computer.state import ActionResult, ComputerAction
from kratos_agent.core.tool_runtime import legacy_tool_registry


class CoordinateFreePolicyTests(unittest.TestCase):
    def test_coordinate_backend_is_not_available(self):
        self.assertFalse(CoordinateBackend().is_available())

    def test_uia_activation_uses_focus_and_keyboard_without_element_bounds(self):
        backend = WindowsUIABackend.__new__(WindowsUIABackend)
        element = GUIElement(id="button-1", name="Continue", role="button", backend="windows_uia")
        focused = ActionResult(ok=True, action="invoke_element", method_used="SetFocus")
        activated = ActionResult(ok=True, action="key_tap", detail="Pressed enter")
        with patch.object(backend, "invoke_element", return_value=focused) as invoke, \
             patch("kratos_agent.computer.gui.input.keyboard.KeyboardEngine.press", return_value=activated) as press:
            result = backend.click_element(element)
        invoke.assert_called_once_with(element, pattern="Invoke")
        press.assert_called_once_with("enter")
        self.assertTrue(result.ok)
        self.assertEqual(result.method_used, "UIA focus + keyboard")

    def test_uia_does_not_type_when_semantic_focus_fails(self):
        backend = WindowsUIABackend.__new__(WindowsUIABackend)
        element = GUIElement(id="textbox-1", name="Search", role="textbox", backend="windows_uia")
        failed = ActionResult(ok=False, action="invoke_element", detail="Could not focus Search")
        with patch.object(backend, "invoke_element", side_effect=[failed, failed]), \
             patch("kratos_agent.computer.gui.input.keyboard.KeyboardEngine.type_text") as type_text:
            result = backend.type_element(element, "private input")
        self.assertFalse(result.ok)
        type_text.assert_not_called()

    def test_executor_does_not_click_a_resolved_element_center(self):
        element = GUIElement(
            id="visual-only",
            name="Continue",
            role="button",
            backend="vision",
            bounds={"x": 20, "y": 30, "w": 40, "h": 20},
        )
        with patch("kratos_agent.computer.executor.get_resolver") as resolver:
            resolver.return_value.resolve.return_value = element
            result = ActionExecutor()._dispatch(
                ComputerAction(action="click", target={"name": "Continue"}),
                tier=1,
            )
        self.assertFalse(result.ok)
        self.assertIn("coordinate input is disabled", result.detail.lower())

    def test_raw_mouse_tools_are_not_model_registered(self):
        registry = legacy_tool_registry(Path.cwd())
        names = {spec.name for spec in registry.specs()}
        self.assertFalse({name for name in names if name.startswith("mouse_") or name in {"gui_mouse", "cursor_position"}})

    def test_scroll_tool_uses_page_keys_and_rejects_horizontal_pointer_scroll(self):
        from kratos_agent.computer.tools.computer_tools import computer_scroll

        expected = ActionResult(ok=True, action="key_tap", detail="pageup")
        with patch("kratos_agent.computer.gui.input.keyboard.KeyboardEngine.press", return_value=expected) as press:
            vertical = json.loads(computer_scroll(dy=100))
            press.assert_called_once_with("pageup")
        self.assertTrue(vertical["ok"])

        horizontal = json.loads(computer_scroll(dy=0, dx=10))
        self.assertFalse(horizontal["ok"])
        self.assertIn("pointer input is disabled", horizontal["detail"])

    def test_browser_click_never_falls_back_to_mouse(self):
        from kratos_agent.utils.computer_tools import browser_click

        with patch("kratos_agent.utils.computer_tools.mouse_click", side_effect=AssertionError("pointer fallback")) as mouse:
            result = json.loads(browser_click(x=20, y=30))
            self.assertFalse(result["ok"])
            result = json.loads(browser_click())
            self.assertFalse(result["ok"])
            mouse.assert_not_called()


if __name__ == "__main__":
    unittest.main()
