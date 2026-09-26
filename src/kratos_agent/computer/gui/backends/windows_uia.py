"""Windows UI Automation (UIA) backend using COM and UIAutomationCore."""
from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

import queue
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

from kratos_agent.computer.gui.backends.base import GUIBackend
from kratos_agent.computer.gui.errors import BackendUnavailableError
from kratos_agent.computer.gui.models import GUIElement
from kratos_agent.computer.state import ActionResult

# Pattern IDs in UI Automation
UIA_InvokePatternId = 10000
UIA_SelectionPatternId = 10001
UIA_ValuePatternId = 10002
UIA_RangeValuePatternId = 10003
UIA_ScrollPatternId = 10004
UIA_ExpandCollapsePatternId = 10005
UIA_TogglePatternId = 10015
UIA_SelectionItemPatternId = 10010
UIA_WindowPatternId = 10009
UIA_TextPatternId = 10014

# Control Type IDs
UIA_ButtonControlTypeId = 50000
UIA_CheckBoxControlTypeId = 50002
UIA_EditControlTypeId = 50004
UIA_ListControlTypeId = 50008
UIA_MenuControlTypeId = 50009
UIA_MenuBarControlTypeId = 50010
UIA_MenuItemControlTypeId = 50011
UIA_TabControlTypeId = 50018
UIA_TabItemControlTypeId = 50019
UIA_TextControlTypeId = 50020
UIA_TreeControlTypeId = 50023
UIA_WindowControlTypeId = 50032

CONTROL_TYPE_NAMES = {
    50000: "Button",
    50001: "Calendar",
    50002: "CheckBox",
    50003: "ComboBox",
    50004: "Edit",
    50005: "Hyperlink",
    50006: "Image",
    50007: "ListItem",
    50008: "List",
    50009: "Menu",
    50010: "MenuBar",
    50011: "MenuItem",
    50012: "ProgressBar",
    50013: "RadioButton",
    50014: "ScrollBar",
    50015: "Slider",
    50016: "Spinner",
    50017: "StatusBar",
    50018: "Tab",
    50019: "TabItem",
    50020: "Text",
    50021: "ToolBar",
    50022: "ToolTip",
    50023: "Tree",
    50024: "TreeItem",
    50025: "Custom",
    50026: "Group",
    50027: "Thumb",
    50028: "DataGrid",
    50029: "DataItem",
    50030: "Document",
    50031: "SplitButton",
    50032: "Window",
    50033: "Pane",
    50034: "Header",
    50035: "HeaderItem",
    50036: "Table",
    50037: "TitleBar",
    50038: "Separator",
}


class _UIAThreadWorker:
    """Dedicated background worker running in a Multi-Threaded Apartment (MTA)."""
    def __init__(self) -> None:
        self.q: queue.Queue = queue.Queue()
        self.available: bool = False
        self._uia: Any = None
        self._walker: Any = None
        self._root: Any = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        # Wait up to 3 seconds for initialization
        deadline = time.time() + 3.0
        while time.time() < deadline and not self.available and self._thread.is_alive():
            time.sleep(0.05)

    def _run(self) -> None:
        if sys.platform != "win32":
            return
        try:
            import comtypes
            import comtypes.client
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
            try:
                comtypes.client.GetModule("UIAutomationCore.dll")
                from comtypes.gen.UIAutomationClient import CUIAutomation, IUIAutomation
                self._uia = comtypes.client.CreateObject(CUIAutomation, interface=IUIAutomation)
                self._walker = self._uia.ControlViewWalker
                self._root = self._uia.GetRootElement()
                self.available = True
            except Exception:
                self.available = False
        except Exception:
            self.available = False

        while True:
            item = self.q.get()
            if item is None:
                break
            func, args, kwargs, res_q = item
            try:
                res = func(self._uia, self._walker, self._root, *args, **kwargs)
                res_q.put((res, None))
            except Exception as e:
                res_q.put((None, e))
            finally:
                self.q.task_done()

    def submit(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if not self.available:
            raise BackendUnavailableError("Windows UI Automation is not available on this system.")
        res_q: queue.Queue = queue.Queue()
        self.q.put((func, args, kwargs, res_q))
        res, err = res_q.get()
        if err:
            raise err
        return res


_worker_instance: _UIAThreadWorker | None = None


def get_uia_worker() -> _UIAThreadWorker:
    global _worker_instance
    if _worker_instance is None:
        _worker_instance = _UIAThreadWorker()
    return _worker_instance


class WindowsUIABackend(GUIBackend):
    """Windows UI Automation backend implementation."""

    def __init__(self) -> None:
        self._worker = get_uia_worker()
        self._native_element_cache: dict[str, Any] = {}

    @property
    def name(self) -> str:
        return "windows_uia"

    @property
    def priority(self) -> int:
        return 2  # Accessibility API = Priority 2

    def is_available(self) -> bool:
        return sys.platform == "win32" and self._worker.available

    def dump_tree(
        self,
        app: str | None = None,
        root_window: str | None = None,
        max_depth: int = 8,
        max_nodes: int = 400,
        visible_only: bool = True,
    ) -> list[GUIElement]:
        if not self.is_available():
            return []

        def _do_dump(uia: Any, walker: Any, root: Any) -> list[GUIElement]:
            elements: list[GUIElement] = []
            elem_id_counter = [1]
            self._native_element_cache.clear()

            def traverse(node: Any, depth: int) -> None:
                if depth > max_depth or len(elements) >= max_nodes or not node:
                    return

                try:
                    is_offscreen = bool(node.CurrentIsOffscreen)
                    if visible_only and is_offscreen:
                        return

                    c_type_id = int(node.CurrentControlType)
                    role = CONTROL_TYPE_NAMES.get(c_type_id, node.CurrentLocalizedControlType or "Control")
                    name = str(node.CurrentName or "").strip()
                    help_text = str(node.CurrentHelpText or "").strip()
                    is_enabled = bool(node.CurrentIsEnabled)

                    # Bounding rect
                    b_rect = node.CurrentBoundingRectangle
                    r = {
                        "x": int(b_rect.left),
                        "y": int(b_rect.top),
                        "w": int(b_rect.right - b_rect.left),
                        "h": int(b_rect.bottom - b_rect.top),
                    }
                    # Skip zero-size invisible elements if visible_only
                    if visible_only and (r["w"] <= 0 or r["h"] <= 0):
                        return

                    elem_id = f"uia_{elem_id_counter[0]}"
                    elem_id_counter[0] += 1
                    self._native_element_cache[elem_id] = node

                    # Read value if available
                    val_str = None
                    try:
                        from comtypes.gen.UIAutomationClient import (
                            IUIAutomationValuePattern,
                        )
                        val_pat = node.GetCurrentPattern(UIA_ValuePatternId)
                        if val_pat:
                            vp = val_pat.QueryInterface(IUIAutomationValuePattern)
                            val_str = vp.CurrentValue
                    except Exception as exc:
                        logger.debug("Operation error suppressed: %s", exc)

                    elem = GUIElement(
                        id=elem_id,
                        name=name,
                        role=role,
                        control_type=str(c_type_id),
                        text=name,
                        value=val_str,
                        description=help_text if help_text else None,
                        enabled=is_enabled,
                        visible=not is_offscreen,
                        focused=bool(node.CurrentHasKeyboardFocus),
                        bounds=r,
                        backend="windows_uia",
                        metadata={"control_type_id": c_type_id},
                        confidence=0.98,
                    )
                    elements.append(elem)

                    # Traverse children
                    child = walker.GetFirstChildElement(node)
                    while child:
                        traverse(child, depth + 1)
                        child = walker.GetNextSiblingElement(child)
                except Exception as exc:
                    logger.debug("Operation error suppressed: %s", exc)

            traverse(root, 0)
            return elements

        try:
            return self._worker.submit(_do_dump)
        except Exception:
            return []

    def find_elements(
        self,
        query: str | None = None,
        role: str | None = None,
        app: str | None = None,
        limit: int = 25,
    ) -> list[GUIElement]:
        tree = self.dump_tree(app=app, max_nodes=500)
        q_lower = query.lower() if query else None
        role_lower = role.lower() if role else None

        matches: list[GUIElement] = []
        for el in tree:
            match = True
            if q_lower:
                el_name = (el.name or "").lower()
                el_text = (el.text or "").lower()
                el_val = (el.value or "").lower()
                match = (q_lower in el_name) or (q_lower in el_text) or (q_lower in el_val)
            if match and role_lower:
                el_role = (el.role or "").lower()
                match = (role_lower == el_role) or (role_lower in el_role)
            if match:
                matches.append(el)
                if len(matches) >= limit:
                    break
        return matches

    def find_element(
        self,
        query: str | None = None,
        role: str | None = None,
        app: str | None = None,
    ) -> GUIElement | None:
        matches = self.find_elements(query=query, role=role, app=app, limit=1)
        return matches[0] if matches else None

    def invoke_element(
        self,
        element: GUIElement,
        pattern: str = "Invoke",
        value: str | None = None,
    ) -> ActionResult:
        """Invokes pattern (Invoke, Value, Toggle, SelectionItem) natively without mouse movement."""
        if not self.is_available():
            return ActionResult(ok=False, action="invoke_element", detail="Windows UIA unavailable")

        node = self._native_element_cache.get(element.id)
        if not node:
            return ActionResult(ok=False, action="invoke_element", detail=f"Element {element.id} not in native cache; refresh state")

        def _do_invoke(uia: Any, walker: Any, root: Any) -> ActionResult:
            import comtypes.gen.UIAutomationClient as uia_types

            # 1. InvokePattern
            if pattern.lower() in ("invoke", "click"):
                try:
                    pat = node.GetCurrentPattern(UIA_InvokePatternId)
                    if pat:
                        inv_pat = pat.QueryInterface(uia_types.IUIAutomationInvokePattern)
                        inv_pat.Invoke()
                        return ActionResult(ok=True, action="invoke_element", detail="Invoked via IUIAutomationInvokePattern", method_used="InvokePattern")
                except Exception as exc:
                    logger.debug("Operation error suppressed: %s", exc)

            # 2. ValuePattern
            if pattern.lower() in ("value", "set_value", "type") and value is not None:
                try:
                    pat = node.GetCurrentPattern(UIA_ValuePatternId)
                    if pat:
                        val_pat = pat.QueryInterface(uia_types.IUIAutomationValuePattern)
                        val_pat.SetValue(value)
                        return ActionResult(ok=True, action="invoke_element", detail=f"Set value via IUIAutomationValuePattern: {value}", method_used="ValuePattern")
                except Exception as exc:
                    logger.debug("Operation error suppressed: %s", exc)

            # 3. TogglePattern
            if pattern.lower() in ("toggle", "check", "uncheck"):
                try:
                    pat = node.GetCurrentPattern(UIA_TogglePatternId)
                    if pat:
                        tog_pat = pat.QueryInterface(uia_types.IUIAutomationTogglePattern)
                        tog_pat.Toggle()
                        return ActionResult(ok=True, action="invoke_element", detail="Toggled via IUIAutomationTogglePattern", method_used="TogglePattern")
                except Exception as exc:
                    logger.debug("Operation error suppressed: %s", exc)

            # 4. SelectionItemPattern
            if pattern.lower() in ("select", "selection"):
                try:
                    pat = node.GetCurrentPattern(UIA_SelectionItemPatternId)
                    if pat:
                        sel_pat = pat.QueryInterface(uia_types.IUIAutomationSelectionItemPattern)
                        sel_pat.Select()
                        return ActionResult(ok=True, action="invoke_element", detail="Selected via IUIAutomationSelectionItemPattern", method_used="SelectionItemPattern")
                except Exception as exc:
                    logger.debug("Operation error suppressed: %s", exc)

            # Fallback: Focus element
            try:
                node.SetFocus()
                return ActionResult(ok=True, action="invoke_element", detail="Focused element (pattern not supported directly)", method_used="SetFocus")
            except Exception as e:
                return ActionResult(ok=False, action="invoke_element", detail=f"Pattern invocation failed: {e}")

        try:
            return self._worker.submit(_do_invoke)
        except Exception as exc:
            return ActionResult(ok=False, action="invoke_element", detail=str(exc))

    def click_element(
        self,
        element: GUIElement,
        button: str = "left",
        clicks: int = 1,
    ) -> ActionResult:
        if button != "left":
            return ActionResult(ok=False, action="click_element", detail="Only semantic activation is supported; pointer buttons are disabled")

        # Prefer native UIA patterns; if unavailable, focus the resolved control
        # and activate it through the keyboard. Never click its bounding-box center.
        role = (element.role or "").lower()
        if "check" in role or "radio" in role:
            pattern, fallback_key = "Toggle", "space"
        elif "selectionitem" in role or "list item" in role:
            pattern, fallback_key = "SelectionItem", "enter"
        else:
            pattern, fallback_key = "Invoke", "enter"

        res = self.invoke_element(element, pattern=pattern)
        if res.ok and res.method_used not in ("SetFocus", "unknown"):
            return res
        if not res.ok:
            return ActionResult(ok=False, action="click_element", detail=res.detail or "UIA could not focus the resolved control")

        from kratos_agent.computer.gui.input.keyboard import KeyboardEngine
        key_result = KeyboardEngine().press(fallback_key)
        return ActionResult(
            ok=key_result.ok,
            action="click_element",
            detail=("Activated focused UIA control with keyboard" if key_result.ok else key_result.detail),
            method_used="UIA focus + keyboard",
            verified=False,
        )

    def type_element(
        self,
        element: GUIElement,
        text: str,
        clear_first: bool = False,
    ) -> ActionResult:
        # First attempt native ValuePattern
        if not clear_first:
            res = self.invoke_element(element, pattern="Value", value=text)
            if res.ok and res.method_used == "ValuePattern":
                return res

        # Fallback: focus and type via keyboard. Never send text to whichever
        # control happened to be focused if UIA could not focus this target.
        focus_result = self.invoke_element(element, pattern="Focus")
        if not focus_result.ok:
            return ActionResult(
                ok=False,
                action="type_element",
                detail=focus_result.detail or "UIA could not focus the resolved input control",
            )
        from kratos_agent.computer.gui.input.keyboard import KeyboardEngine
        kb = KeyboardEngine()
        if clear_first:
            kb.hotkey("ctrl", "a")
            kb.key_tap(["backspace"])
        return kb.type_text(text)
