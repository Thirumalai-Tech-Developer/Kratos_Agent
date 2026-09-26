"""Core computer control tools for the agent runtime."""
from __future__ import annotations

import json

from kratos_agent.ccs.perception.screenshot import take_screenshot
from kratos_agent.computer.gui.manager import get_gui_manager
from kratos_agent.computer.manager import get_computer_manager
from kratos_agent.computer.state import ComputerAction


def computer_observe(include_interactive: bool = True, max_elements: int = 100) -> str:
    """Captures a complete, compact observation of the computer environment (windows, apps, interactive controls)."""
    cm = get_computer_manager()
    state = cm.observe(include_interactive=include_interactive, max_elements=max_elements)
    return json.dumps(state.to_dict(), indent=2)


def computer_inspect(query: str | None = None, role: str | None = None, app: str | None = None) -> str:
    """Inspects the current UI to find controls matching semantic criteria without acting on them."""
    gm = get_gui_manager()
    try:
        elem = gm.find(query=query, role=role)
        return json.dumps(elem.to_dict(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=2)


def computer_find(query: str, role: str | None = None) -> str:
    """Finds a specific UI control by label, text, or accessibility name."""
    return computer_inspect(query=query, role=role)


def computer_click(name: str | None = None, role: str | None = None, id: str | None = None, button: str = "left") -> str:
    """Activates a semantic UI element by accessible name or role without pointer coordinates."""
    cm = get_computer_manager()
    target = {}
    if name: target["name"] = name
    if role: target["role"] = role
    if id: target["id"] = id
    action = ComputerAction(action="click", target=target, parameters={"button": button})
    res = cm.execute_action(action)
    return json.dumps(res.to_dict(), indent=2)


def computer_type(text: str, name: str | None = None, role: str | None = None, id: str | None = None) -> str:
    """Enters text into an input field, textbox, or active editor."""
    cm = get_computer_manager()
    target = {}
    if name: target["name"] = name
    if role: target["role"] = role
    if id: target["id"] = id
    action = ComputerAction(action="type", target=target if target else None, parameters={"text": text})
    res = cm.execute_action(action)
    return json.dumps(res.to_dict(), indent=2)


def computer_press(key: str) -> str:
    """Presses a single key (e.g. 'enter', 'escape', 'tab', 'backspace')."""
    cm = get_computer_manager()
    action = ComputerAction(action="press", parameters={"key": key})
    res = cm.execute_action(action)
    return json.dumps(res.to_dict(), indent=2)


def computer_hotkey(keys: str) -> str:
    """Executes a keyboard hotkey combination (e.g. 'ctrl+s', 'alt+tab', 'ctrl+shift+p')."""
    cm = get_computer_manager()
    action = ComputerAction(action="hotkey", parameters={"keys": [k.strip() for k in keys.split("+")]})
    res = cm.execute_action(action)
    return json.dumps(res.to_dict(), indent=2)


def computer_scroll(dy: int, dx: int = 0) -> str:
    """Scrolls the focused control with Page Up/Down keys (positive dy is up)."""
    from kratos_agent.computer.gui.input.keyboard import KeyboardEngine
    if dx:
        return json.dumps({"ok": False, "action": "computer_scroll", "detail": "Horizontal scrolling requires a semantic scroll target; pointer input is disabled."}, indent=2)
    if not dy:
        return json.dumps({"ok": True, "action": "computer_scroll", "detail": "No vertical scrolling requested."}, indent=2)
    res = KeyboardEngine().press("pageup" if dy > 0 else "pagedown")
    return json.dumps(res.to_dict(), indent=2)


def computer_focus(window_title: str | None = None, window_id: str | None = None) -> str:
    """Brings a window into focus by title or handle."""
    cm = get_computer_manager()
    action = ComputerAction(action="window_focus", parameters={"title_regex": window_title, "handle": window_id})
    res = cm.execute_action(action)
    return json.dumps(res.to_dict(), indent=2)


def computer_launch(target: str, args: list[str] | None = None) -> str:
    """Launches an application, executable, or URI."""
    cm = get_computer_manager()
    action = ComputerAction(action="app_launch", parameters={"target": target, "args": args or []})
    res = cm.execute_action(action)
    return json.dumps(res.to_dict(), indent=2)


def computer_close(window_id: str | None = None, window_title: str | None = None) -> str:
    """Closes an open window."""
    cm = get_computer_manager()
    action = ComputerAction(action="window_close", target={"id": window_id, "name": window_title})
    res = cm.execute_action(action)
    return json.dumps(res.to_dict(), indent=2)


def computer_window_list() -> str:
    """Lists all open windows with their titles and IDs."""
    from kratos_agent.computer.apps.windows import get_window_manager
    wins = get_window_manager().list_windows()
    return json.dumps([w.to_dict() for w in wins], indent=2)


def computer_window_focus(target: str) -> str:
    """Focuses a window by title or handle."""
    return computer_focus(window_title=target)


def computer_screenshot() -> str:
    """Captures a screenshot of the display."""
    try:
        data, ref = take_screenshot()
        return json.dumps({"ok": True, "frame_ref": ref, "bytes": len(data)}, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


def computer_clipboard_read() -> str:
    """Reads current text from the clipboard."""
    from kratos_agent.computer.filesystem.clipboard import get_clipboard_engine
    return get_clipboard_engine().read()


def computer_clipboard_write(text: str) -> str:
    """Copies text to the clipboard."""
    from kratos_agent.computer.filesystem.clipboard import get_clipboard_engine
    res = get_clipboard_engine().write(text)
    return json.dumps(res.to_dict(), indent=2)
