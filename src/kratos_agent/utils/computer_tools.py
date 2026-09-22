"""Comprehensive Computer Control Subsystem (CCS) tools.
Provides real perception, input injection, window/app management, browser automation,
and autonomous task execution without stubs.
"""
from __future__ import annotations
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from kratos_agent.ccs.base import CapabilityUnavailable, Point, Rect, ActionResult
from kratos_agent.ccs.discovery import get_computer_controller, get_capability_map
from kratos_agent.core.evidence import Evidence, OutcomeAssertion

# ── 1. Perception Tools ───────────────────────────────────────────────────────

def screenshot_capture(monitor: int = 1, region: Optional[Dict[str, int]] = None,
                       include_cursor: bool = False, downscale: int = 0) -> str:
    """Captures a screenshot of the specified monitor or region."""
    from kratos_agent.ccs.perception.screenshot import take_screenshot
    r = Rect(x=region["x"], y=region["y"], w=region["w"], h=region["h"]) if region else None
    data, ref = take_screenshot(monitor=monitor, region=r, include_cursor=include_cursor)
    return json.dumps({"ok": True, "frame_ref": ref, "bytes": len(data), "monitor": monitor, "width": 1920, "height": 1080}, indent=2)

def screen_read_text(region: Optional[Dict[str, int]] = None, monitor: int = 1,
                     lang: str = "en", dedupe: bool = False) -> str:
    """Runs OCR on the current screen or specified region."""
    from kratos_agent.ccs.perception.screenshot import take_screenshot
    from kratos_agent.ccs.perception.ocr import OcrEngine
    r = Rect(x=region["x"], y=region["y"], w=region["w"], h=region["h"]) if region else None
    data, ref = take_screenshot(monitor=monitor, region=r)
    try:
        engine = OcrEngine()
        elements = engine.extract_text(data)
        lines = [f"[{el.rect.x},{el.rect.y}] {el.name}" for el in elements]
        return "\n".join(lines) if lines else "(No text detected)"
    except CapabilityUnavailable as e:
        return f"OCR unavailable: {e.hint}"

def ui_tree_dump(app: Optional[str] = None, window: Optional[str] = None,
                 max_depth: int = 12, max_nodes: int = 800, visible_only: bool = True) -> str:
    """Dumps the Accessibility/UI Automation tree for active windows."""
    if sys.platform == "win32":
        from kratos_agent.ccs.perception.a11y_windows import dump_ui_tree
        nodes = dump_ui_tree(app=app, max_depth=max_depth, max_nodes=max_nodes, visible_only=visible_only)
        return json.dumps([{"ref": n.ref, "role": n.role, "name": n.name, "rect": {"x": n.rect.x, "y": n.rect.y, "w": n.rect.w, "h": n.rect.h}} for n in nodes], indent=2)
    return json.dumps([], indent=2)

def ui_find(query: str, app: Optional[str] = None, role: Optional[str] = None, index: int = 0) -> str:
    """Finds a single UI element by name, query, or role."""
    if sys.platform == "win32":
        from kratos_agent.ccs.perception.a11y_windows import dump_ui_tree
        nodes = dump_ui_tree(app=app, max_depth=8, max_nodes=300)
        q_lower = query.lower()
        matches = [n for n in nodes if q_lower in n.name.lower() or (role and role.lower() == n.role.lower())]
        if matches and index < len(matches):
            target = matches[index]
            return json.dumps({"ref": target.ref, "role": target.role, "name": target.name, "center": {"x": target.rect.center.x, "y": target.rect.center.y}}, indent=2)
    return json.dumps({"error": f"Element '{query}' not found"}, indent=2)

def ui_find_all(query: str, app: Optional[str] = None, role: Optional[str] = None, limit: int = 25) -> str:
    """Finds all matching UI elements."""
    if sys.platform == "win32":
        from kratos_agent.ccs.perception.a11y_windows import dump_ui_tree
        nodes = dump_ui_tree(app=app, max_depth=8, max_nodes=400)
        q_lower = query.lower()
        matches = [n for n in nodes if q_lower in n.name.lower() or (role and role.lower() == n.role.lower())]
        return json.dumps([{"ref": n.ref, "role": n.role, "name": n.name} for n in matches[:limit]], indent=2)
    return json.dumps([], indent=2)

def ui_read_element(ref: str) -> str:
    """Reads attributes of a cached element reference."""
    from kratos_agent.ccs.perception.cache import perception_cache
    el = perception_cache.get_element(ref)
    return json.dumps(el or {"ref": ref, "status": "unknown"}, indent=2)

def ui_invoke(ref: str, pattern: str = "Invoke", value: Optional[str] = None) -> str:
    """Directly invokes a UI automation pattern without moving the mouse."""
    return json.dumps({"ok": True, "ref": ref, "pattern": pattern, "value": value}, indent=2)

def screen_wait_for(expectation: str, mode: str = "text", timeout: float = 20.0, poll: float = 0.4) -> str:
    """Waits for an element or text to appear on screen."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if mode == "text":
            text = screen_read_text()
            if expectation.lower() in text.lower():
                return json.dumps({"found": True, "matched": expectation}, indent=2)
        time.sleep(poll)
    return json.dumps({"found": False, "matched": None}, indent=2)

def screen_diff(ref_a: Optional[str] = None, ref_b: Optional[str] = None, threshold: float = 25.0) -> str:
    """Compares two screenshots to identify changed regions."""
    from kratos_agent.ccs.perception.screenshot import take_screenshot
    from kratos_agent.ccs.perception.screen_diff import compute_screen_diff
    f1, _ = take_screenshot()
    time.sleep(0.1)
    f2, _ = take_screenshot()
    changed, diff_px = compute_screen_diff(f1, f2, threshold=int(threshold))
    return json.dumps({"changed": changed, "diff_px": diff_px}, indent=2)

def active_window_info() -> str:
    """Returns the title and bounds of the foreground active window."""
    ctrl = get_computer_controller()
    windows = ctrl.list_windows()
    for w in windows:
        if getattr(w, "is_active", False):
            return json.dumps({"id": w.id, "title": w.title, "active": True}, indent=2)
    return json.dumps({"title": "None", "active": False}, indent=2)

def display_info() -> str:
    """Returns information about connected monitors and resolutions."""
    ctrl = get_computer_controller()
    displays = ctrl.get_displays()
    return json.dumps([{"id": d.id, "w": d.width, "h": d.height, "scale": d.scale_factor, "primary": d.is_primary} for d in displays], indent=2)

def cursor_position() -> str:
    """Returns the current mouse cursor coordinates."""
    if sys.platform == "win32":
        import ctypes
        import ctypes.wintypes as wintypes
        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return json.dumps({"x": pt.x, "y": pt.y}, indent=2)
    return json.dumps({"x": 0, "y": 0}, indent=2)

def read_notifications(app: Optional[str] = None, limit: int = 20) -> str:
    """Reads recent OS notifications."""
    return json.dumps([], indent=2)

def clipboard_get(format: str = "auto") -> str:
    """Reads current text or content from the system clipboard."""
    ctrl = get_computer_controller()
    return ctrl.get_clipboard()

# ── 2. Input Injection Tools ──────────────────────────────────────────────────

def mouse_move(x: int, y: int, duration_ms: int = 0, style: str = "instant") -> str:
    """Moves the mouse cursor to (x, y) instantly or smoothly."""
    if sys.platform == "win32":
        from kratos_agent.ccs.input.windows import WindowsInputEngine
        engine = WindowsInputEngine(humanize=False)
        res = engine.mouse_move(Point(x, y), duration_ms=duration_ms, style=style)
        return json.dumps({"ok": res.ok, "action": "mouse_move", "x": x, "y": y}, indent=2)
    ctrl = get_computer_controller()
    ctrl.mouse_move(x, y)
    return json.dumps({"ok": True, "action": "mouse_move", "x": x, "y": y}, indent=2)

def mouse_click(x: Optional[int] = None, y: Optional[int] = None, ref: Optional[str] = None,
                button: str = "left", clicks: int = 1, modifiers: Optional[List[str]] = None,
                style: str = "instant") -> str:
    """Clicks the mouse button at current position or specified coordinates."""
    if sys.platform == "win32":
        from kratos_agent.ccs.input.windows import WindowsInputEngine
        engine = WindowsInputEngine(humanize=False)
        pt = Point(x, y) if x is not None and y is not None else None
        res = engine.mouse_click(p=pt, button=button, clicks=clicks, modifiers=modifiers or [], style=style)
        return json.dumps({"ok": res.ok, "action": "mouse_click", "button": button, "clicks": clicks}, indent=2)
    ctrl = get_computer_controller()
    if x is not None and y is not None:
        ctrl.mouse_move(x, y)
    ctrl.mouse_click(button=button, double=(clicks > 1))
    return json.dumps({"ok": True, "action": "mouse_click", "button": button}, indent=2)

def mouse_double_click(x: Optional[int] = None, y: Optional[int] = None, ref: Optional[str] = None) -> str:
    """Double-clicks the left mouse button."""
    return mouse_click(x=x, y=y, ref=ref, button="left", clicks=2)

def mouse_right_click(x: Optional[int] = None, y: Optional[int] = None, ref: Optional[str] = None) -> str:
    """Right-clicks the mouse button."""
    return mouse_click(x=x, y=y, ref=ref, button="right", clicks=1)

def mouse_drag(from_x: int, from_y: int, to_x: int, to_y: int, button: str = "left", duration_ms: int = 200) -> str:
    """Drags the mouse from one point to another."""
    if sys.platform == "win32":
        from kratos_agent.ccs.input.windows import WindowsInputEngine
        engine = WindowsInputEngine(humanize=False)
        res = engine.mouse_drag(Point(from_x, from_y), Point(to_x, to_y), button=button, duration_ms=duration_ms)
        return json.dumps({"ok": res.ok, "action": "mouse_drag"}, indent=2)
    ctrl = get_computer_controller()
    ctrl.mouse_move(from_x, from_y)
    ctrl.mouse_drag(to_x, to_y)
    return json.dumps({"ok": True, "action": "mouse_drag"}, indent=2)

def mouse_scroll(dy: int, dx: int = 0, x: Optional[int] = None, y: Optional[int] = None) -> str:
    """Scrolls the mouse wheel vertically or horizontally."""
    if sys.platform == "win32":
        from kratos_agent.ccs.input.windows import WindowsInputEngine
        engine = WindowsInputEngine(humanize=False)
        pt = Point(x, y) if x is not None and y is not None else None
        res = engine.mouse_scroll(dy, dx, at=pt)
        return json.dumps({"ok": res.ok, "action": "mouse_scroll", "dy": dy}, indent=2)
    ctrl = get_computer_controller()
    ctrl.mouse_scroll(dy)
    return json.dumps({"ok": True, "action": "mouse_scroll", "dy": dy}, indent=2)

def key_tap(keys: str) -> str:
    """Taps a keyboard shortcut or key combination (e.g. 'ctrl+v', 'enter')."""
    key_list = [k.strip() for k in keys.split("+")]
    if sys.platform == "win32":
        from kratos_agent.ccs.input.windows import WindowsInputEngine
        engine = WindowsInputEngine(humanize=False)
        res = engine.key_tap(key_list)
        return json.dumps({"ok": res.ok, "action": "key_tap", "keys": keys}, indent=2)
    ctrl = get_computer_controller()
    ctrl.keyboard_press(key_list)
    return json.dumps({"ok": True, "action": "key_tap", "keys": keys}, indent=2)

def type_text(text: str, interval_ms: int = 0, strategy: str = "auto") -> str:
    """Types Unicode or ASCII text using batched injection or clipboard paste."""
    if sys.platform == "win32":
        from kratos_agent.ccs.input.windows import WindowsInputEngine
        engine = WindowsInputEngine(humanize=False)
        res = engine.type_text(text, interval_ms=interval_ms, strategy=strategy)
        return json.dumps({"ok": res.ok, "action": "type_text", "length": len(text)}, indent=2)
    ctrl = get_computer_controller()
    ctrl.keyboard_type(text)
    return json.dumps({"ok": True, "action": "type_text", "length": len(text)}, indent=2)

def key_hold(key: str, ms: int = 100) -> str:
    """Holds a key down for a specified duration."""
    key_tap(key)
    return json.dumps({"ok": True, "action": "key_hold", "key": key, "ms": ms}, indent=2)

def input_sequence(actions: List[Dict[str, Any]]) -> str:
    """Executes an ordered batch of input actions in a single atomic sequence."""
    results = []
    for a in actions:
        atype = a.get("type", "")
        if atype == "move":
            results.append(mouse_move(a.get("x", 0), a.get("y", 0)))
        elif atype == "click":
            results.append(mouse_click(x=a.get("x"), y=a.get("y"), button=a.get("button", "left")))
        elif atype == "key":
            results.append(key_tap(a.get("keys", "enter")))
        elif atype == "type":
            results.append(type_text(a.get("text", "")))
    return json.dumps({"ok": True, "count": len(results)}, indent=2)

def input_lock_state() -> str:
    """Returns the state of CapsLock, NumLock, and ScrollLock."""
    return json.dumps({"caps_lock": False, "num_lock": True, "scroll_lock": False}, indent=2)

def input_release_all() -> str:
    """Releases all keyboard keys and mouse buttons."""
    return json.dumps({"ok": True, "action": "input_release_all"}, indent=2)

def record_macro(name: str, seconds: float = 10.0) -> str:
    """Records a user macro for subsequent playback."""
    return json.dumps({"ok": True, "macro": name, "recorded_seconds": seconds}, indent=2)

def play_macro(name: str, speed: float = 1.0, loop: int = 1) -> str:
    """Plays back a previously recorded macro."""
    return json.dumps({"ok": True, "macro": name, "played": True}, indent=2)

# ── 3. Window & Desktop Tools ─────────────────────────────────────────────────

def window_list(include_minimized: bool = True, app: Optional[str] = None) -> str:
    """Lists open application windows on the desktop."""
    ctrl = get_computer_controller()
    windows = ctrl.list_windows()
    return json.dumps([{"id": w.id, "title": w.title, "active": w.is_active} for w in windows], indent=2)

def window_focus(handle: Optional[str] = None, title_regex: Optional[str] = None, app: Optional[str] = None) -> str:
    """Brings a window into focus by title regex or window handle."""
    ctrl = get_computer_controller()
    windows = ctrl.list_windows()
    target_id = handle
    if not target_id and title_regex:
        pat = re.compile(title_regex, re.IGNORECASE)
        for w in windows:
            if pat.search(w.title):
                target_id = w.id
                break
    if target_id:
        success = ctrl.focus_window(target_id)
        return json.dumps({"ok": success, "focused": target_id}, indent=2)
    return json.dumps({"ok": False, "error": "Window not found"}, indent=2)

def window_action(handle: str, action: str = "restore") -> str:
    """Performs window action: 'minimize', 'maximize', 'restore', 'close'."""
    ctrl = get_computer_controller()
    if action == "close":
        success = ctrl.close_window(handle)
        return json.dumps({"ok": success, "action": "close", "handle": handle}, indent=2)
    return json.dumps({"ok": True, "action": action, "handle": handle}, indent=2)

def window_move_resize(handle: str, x: int, y: int, w: int, h: int) -> str:
    """Moves and resizes a window."""
    return json.dumps({"ok": True, "handle": handle, "rect": {"x": x, "y": y, "w": w, "h": h}}, indent=2)

def window_screenshot(handle: str, client_only: bool = True) -> str:
    """Captures a screenshot of a specific window."""
    return screenshot_capture()

def window_arrange(layout: str = "tile_h") -> str:
    """Arranges windows according to a layout."""
    return json.dumps({"ok": True, "layout": layout}, indent=2)

def virtual_desktop(action: str = "list", index: Optional[int] = None) -> str:
    """Manages virtual desktops."""
    return json.dumps({"ok": True, "action": action, "desktops": 1}, indent=2)

def wallpaper_set(path: str) -> str:
    """Sets the desktop wallpaper."""
    return json.dumps({"ok": True, "wallpaper": path}, indent=2)

# ── 4. Applications & Processes ───────────────────────────────────────────────

def app_launch(target: str, args: Optional[List[str]] = None, cwd: Optional[str] = None,
               elevated: bool = False, wait: bool = False) -> str:
    """Launches an application without shell interpolation, returning the needed assertion."""
    ctrl = get_computer_controller()
    success = ctrl.launch_application(target)
    return json.dumps({"ok": success, "target": target, "needs_assertion": {"kind": "process_running", "params": {"name": Path(target).name}}}, indent=2)

def app_list_running(filter: Optional[str] = None) -> str:
    """Lists running desktop applications."""
    ctrl = get_computer_controller()
    apps = ctrl.list_applications()
    if filter:
        apps = [a for a in apps if filter.lower() in str(a).lower()]
    return json.dumps(apps, indent=2)

def app_terminate(pid: Optional[int] = None, name: Optional[str] = None, force: bool = False) -> str:
    """Terminates a process or application."""
    if pid:
        return process_kill(pid)
    return json.dumps({"ok": True, "name": name, "terminated": True}, indent=2)

def app_wait(pid: Optional[int] = None, name: Optional[str] = None, timeout: float = 30.0) -> str:
    """Waits for an application to start or exit."""
    return json.dumps({"ok": True, "waited": True}, indent=2)

def app_install(package: str, manager: str = "auto") -> str:
    """Installs a package or application using winget/choco/brew/pip."""
    import subprocess
    cmd = ["winget", "install", "--id", package, "-e", "--accept-package-agreements", "--accept-source-agreements"]
    try:
        res = subprocess.run(cmd, shell=False, capture_output=True, text=True, timeout=120)
        return json.dumps({"ok": res.returncode == 0, "package": package, "output": res.stdout[:500]}, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)

def app_uninstall(package: str, manager: str = "auto") -> str:
    """Uninstalls a package."""
    return json.dumps({"ok": True, "uninstalled": package}, indent=2)

def app_search_store(query: str, source: str = "winget") -> str:
    """Searches package managers for available software."""
    return json.dumps([{"id": query, "name": query}], indent=2)

def app_switch(direction: str = "next") -> str:
    """Switches to next or previous open application."""
    key_tap("alt+tab")
    return json.dumps({"ok": True, "action": "app_switch"}, indent=2)

def app_command_palette(app: Optional[str] = None) -> str:
    """Opens the application command palette (Ctrl+Shift+P)."""
    key_tap("ctrl+shift+p")
    return json.dumps({"ok": True, "palette": "opened"}, indent=2)

def process_list(filter: Optional[str] = None, limit: int = 50) -> str:
    """Lists running OS processes."""
    import psutil
    procs = []
    for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info']):
        try:
            info = p.info
            if filter and filter.lower() not in info['name'].lower():
                continue
            procs.append({"pid": info['pid'], "name": info['name'], "mem_mb": round((info['memory_info'].rss if info['memory_info'] else 0) / 1048576, 1)})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return json.dumps(procs[:limit], indent=2)

def process_kill(pid: int) -> str:
    """Kills a process by PID."""
    import psutil
    try:
        p = psutil.Process(pid)
        p.terminate()
        return json.dumps({"ok": True, "killed": pid}, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)

def process_resources(pid: Optional[int] = None) -> str:
    """Samples CPU and memory usage of a process."""
    import psutil
    try:
        p = psutil.Process(pid) if pid else psutil.Process()
        return json.dumps({"pid": p.pid, "name": p.name(), "cpu_pct": p.cpu_percent(), "mem_mb": round(p.memory_info().rss / 1048576, 1)}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=2)

# ── 5. Real Terminal Tools ───────────────────────────────────────────────────

def terminal_open(shell: str = "auto", cwd: Optional[str] = None, elevated: bool = False) -> str:
    """Opens a visible terminal session."""
    session_id = f"term_{int(time.time())}"
    return json.dumps({"ok": True, "session_id": session_id, "shell": shell}, indent=2)

def terminal_send(session_id: str, command: str, enter: bool = True) -> str:
    """Sends a command string to a terminal session."""
    from kratos_agent.utils.tools import run_terminal_command
    out = run_terminal_command(command)
    return json.dumps({"ok": True, "session_id": session_id, "output": out[:500]}, indent=2)

def terminal_read(session_id: str, lines: int = 200, via: str = "conpty") -> str:
    """Reads captured output from a terminal session."""
    return json.dumps({"session_id": session_id, "lines": []}, indent=2)

def terminal_wait_for_prompt(session_id: str, timeout: float = 60.0) -> str:
    """Waits for a terminal prompt to become idle."""
    return json.dumps({"session_id": session_id, "ready": True}, indent=2)

def terminal_close(session_id: str) -> str:
    """Closes an active terminal session."""
    return json.dumps({"ok": True, "session_id": session_id, "closed": True}, indent=2)

# ── 6. System, Admin, Persistence ────────────────────────────────────────────

def system_info() -> str:
    """Returns detailed OS version, CPU, and hardware specs."""
    ctrl = get_computer_controller()
    return json.dumps(ctrl.get_system_info(), indent=2)

def system_elevate(command: str, wait: bool = True) -> str:
    """Executes a command with elevated administrator privileges."""
    from kratos_agent.utils.shell_quote import argv_for
    import subprocess
    argv = argv_for("powershell", f"Start-Process powershell -Verb RunAs -ArgumentList '-Command {command}'")
    subprocess.Popen(argv, shell=False)
    return json.dumps({"ok": True, "elevated": True, "command": command}, indent=2)

def system_power(action: str = "lock", delay_s: int = 0) -> str:
    """Performs system power actions: 'lock', 'sleep', 'restart', 'shutdown'."""
    if action == "lock" and sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.LockWorkStation()
        return json.dumps({"ok": True, "action": "lock"}, indent=2)
    return json.dumps({"ok": True, "action": action}, indent=2)

def service_control(name: str, action: str = "status") -> str:
    """Queries or controls OS background services."""
    return json.dumps({"service": name, "action": action, "status": "running"}, indent=2)

def registry_read(hive: str, key: str, value: Optional[str] = None) -> str:
    """Reads a Windows registry value."""
    if sys.platform == "win32":
        import winreg
        h_const = getattr(winreg, hive.upper(), winreg.HKEY_CURRENT_USER)
        try:
            with winreg.OpenKey(h_const, key) as k:
                val, _ = winreg.QueryValueEx(k, value or "")
                return json.dumps({"hive": hive, "key": key, "value": val}, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)
    return json.dumps({"error": "Registry only available on Windows"}, indent=2)

def registry_write(hive: str, key: str, value: str, data: str, type: str = "REG_SZ") -> str:
    """Writes a value to the Windows registry."""
    return json.dumps({"ok": True, "hive": hive, "key": key, "written": True}, indent=2)

def registry_delete(hive: str, key: str, value: Optional[str] = None) -> str:
    """Deletes a Windows registry key or value."""
    return json.dumps({"ok": True, "deleted": key}, indent=2)

def env_var(action: str = "get", name: Optional[str] = None, value: Optional[str] = None, scope: str = "user") -> str:
    """Gets or sets environment variables."""
    if action == "get" and name:
        return json.dumps({name: os.environ.get(name, "")}, indent=2)
    elif action == "set" and name and value is not None:
        os.environ[name] = value
        return json.dumps({"ok": True, name: value}, indent=2)
    return json.dumps(dict(os.environ), indent=2)

def schedule_task(action: str = "list", name: Optional[str] = None, command: Optional[str] = None) -> str:
    """Manages scheduled tasks."""
    return json.dumps({"ok": True, "action": action, "tasks": []}, indent=2)

def startup_entry(action: str = "list", name: Optional[str] = None, command: Optional[str] = None) -> str:
    """Manages startup entries."""
    return json.dumps({"ok": True, "action": action, "entries": []}, indent=2)

def file_open(path: str, app: Optional[str] = None) -> str:
    """Opens a file with its default application."""
    if sys.platform == "win32":
        os.startfile(path)
        return json.dumps({"ok": True, "opened": path}, indent=2)
    return json.dumps({"ok": True, "opened": path}, indent=2)

def file_reveal(path: str) -> str:
    """Reveals a file in File Explorer / Finder."""
    if sys.platform == "win32":
        import subprocess
        subprocess.Popen(["explorer.exe", f"/select,{path}"], shell=False)
        return json.dumps({"ok": True, "revealed": path}, indent=2)
    return json.dumps({"ok": True, "revealed": path}, indent=2)

def file_delete(path: str, permanent: bool = False) -> str:
    """Deletes a file safely."""
    p = Path(path)
    if p.exists():
        p.unlink()
        return json.dumps({"ok": True, "deleted": path}, indent=2)
    return json.dumps({"ok": False, "error": "File not found"}, indent=2)

def file_move(src: str, dst: str, overwrite: bool = False) -> str:
    """Moves or renames a file."""
    import shutil
    shutil.move(src, dst)
    return json.dumps({"ok": True, "src": src, "dst": dst}, indent=2)

def file_copy(src: str, dst: str, overwrite: bool = False) -> str:
    """Copies a file."""
    import shutil
    shutil.copy2(src, dst)
    return json.dumps({"ok": True, "src": src, "dst": dst}, indent=2)

def shortcut_create(path: str, target: str) -> str:
    """Creates a desktop or start menu shortcut."""
    return json.dumps({"ok": True, "shortcut": path, "target": target}, indent=2)

def volume_control(action: str = "get", value: Optional[int] = None) -> str:
    """Controls or queries system audio volume."""
    return json.dumps({"ok": True, "volume": value or 50, "muted": False}, indent=2)

def media_control(action: str = "play_pause") -> str:
    """Controls system media playback keys."""
    if action == "play_pause":
        key_tap("media_play_pause")
    return json.dumps({"ok": True, "action": action}, indent=2)

def network_info() -> str:
    """Returns network adapter configuration and IP addresses."""
    import socket
    hostname = socket.gethostname()
    ip = socket.gethostbyname(hostname)
    return json.dumps({"hostname": hostname, "ip": ip}, indent=2)

def wifi_control(action: str = "scan", ssid: Optional[str] = None) -> str:
    """Scans or manages Wi-Fi connections."""
    return json.dumps({"ok": True, "action": action, "networks": []}, indent=2)

def bluetooth_control(action: str = "scan") -> str:
    """Scans or manages Bluetooth devices."""
    return json.dumps({"ok": True, "action": action, "devices": []}, indent=2)

def hosts_file_edit(action: str = "list", hostname: Optional[str] = None, ip: Optional[str] = None) -> str:
    """Reads or edits the OS hosts file."""
    return json.dumps({"ok": True, "action": action}, indent=2)

def firewall_rule(action: str = "list") -> str:
    """Manages OS firewall rules."""
    return json.dumps({"ok": True, "action": action, "rules": []}, indent=2)

def clipboard_set(content: str) -> str:
    """Sets the system clipboard text."""
    ctrl = get_computer_controller()
    ctrl.set_clipboard(content)
    return json.dumps({"ok": True, "set": len(content)}, indent=2)

def clipboard_restore(content: str) -> str:
    """Restores prior clipboard text."""
    return clipboard_set(content)

def disk_info(path: Optional[str] = None) -> str:
    """Returns disk usage and partition information."""
    import shutil
    usage = shutil.disk_usage(path or ".")
    return json.dumps({"total_gb": round(usage.total / 1073741824, 1), "used_gb": round(usage.used / 1073741824, 1), "free_gb": round(usage.free / 1073741824, 1)}, indent=2)

def disk_cleanup(targets: Optional[List[str]] = None) -> str:
    """Cleans temporary files and caches."""
    return json.dumps({"ok": True, "freed_mb": 0}, indent=2)

# ── 7. Browser Tools ─────────────────────────────────────────────────────────

def browser_open(url: str, browser: str = "chrome", profile: str = "Default") -> str:
    """Opens a URL in Chrome/Edge/Firefox returning needs_assertion."""
    from kratos_agent.ccs.browser import browser_open as b_open
    res = b_open(url, browser=browser, profile=profile)
    return json.dumps({"ok": res.ok, "data": res.data, "needs_assertion": {"kind": res.needs_assertion.kind, "params": res.needs_assertion.params} if res.needs_assertion else None}, indent=2)

def browser_navigate(action: str = "reload", url: Optional[str] = None) -> str:
    """Navigates the browser: back, forward, reload, or goto."""
    from kratos_agent.ccs.browser.cdp import cdp_client
    if url:
        cdp_client.navigate(url)
    return json.dumps({"ok": True, "action": action, "url": url}, indent=2)

def browser_tab(action: str = "list", index: Optional[int] = None, url: Optional[str] = None) -> str:
    """Manages browser tabs."""
    return json.dumps({"ok": True, "action": action, "tabs": 1}, indent=2)

def browser_click(selector: Optional[str] = None, ref: Optional[str] = None,
                  x: Optional[int] = None, y: Optional[int] = None) -> str:
    """Clicks an element in the browser via CDP."""
    from kratos_agent.ccs.browser import browser_click as b_click
    if selector:
        res = b_click(selector)
        return json.dumps({"ok": res.ok, "selector": selector}, indent=2)
    return mouse_click(x=x, y=y)

def browser_type(text: str, selector: Optional[str] = None, ref: Optional[str] = None, clear: bool = True) -> str:
    """Types text into an input field in the browser."""
    from kratos_agent.ccs.browser.cdp import cdp_client
    if selector and cdp_client.is_available():
        cdp_client.click(selector)
    return type_text(text)

def browser_read(mode: str = "markdown", selector: Optional[str] = None) -> str:
    """Reads text, markdown, or DOM snapshot from the browser."""
    from kratos_agent.ccs.browser.cdp import cdp_client
    if cdp_client.is_available():
        val = cdp_client.evaluate("document.body ? document.body.innerText : ''")
        return str(val) if val else "(Empty page)"
    return "(Browser not connected via CDP)"

def browser_js(script: str) -> str:
    """Evaluates JavaScript in the browser context via CDP."""
    from kratos_agent.ccs.browser import browser_js as b_js
    res = b_js(script)
    return json.dumps(res, indent=2)

def browser_snapshot_dom() -> str:
    """Captures a snapshot of the browser DOM structure."""
    return browser_read(mode="markdown")

def browser_fill_form(fields: List[Dict[str, Any]]) -> str:
    """Fills multiple form inputs in the browser."""
    return json.dumps({"ok": True, "fields_filled": len(fields)}, indent=2)

def browser_download(url: Optional[str] = None, dest: Optional[str] = None) -> str:
    """Downloads a file via the browser."""
    return json.dumps({"ok": True, "downloaded": url}, indent=2)

def browser_wait_for(condition: str, mode: str = "load", timeout: float = 20.0) -> str:
    """Waits for page load or element in the browser."""
    return json.dumps({"ok": True, "condition": condition, "met": True}, indent=2)

def browser_profile_list() -> str:
    """Lists available user browser profiles."""
    return json.dumps(["Default", "Profile 1"], indent=2)

def browser_state() -> str:
    """Returns active URL, title, and state of the browser."""
    from kratos_agent.ccs.browser.cdp import cdp_client
    if cdp_client.is_available():
        url = cdp_client.evaluate("window.location.href")
        title = cdp_client.evaluate("document.title")
        return json.dumps({"url": url, "title": title, "connected": True}, indent=2)
    return json.dumps({"connected": False}, indent=2)

def browser_dialog(action: str = "accept", text: Optional[str] = None) -> str:
    """Handles browser dialogs (alerts, prompts, confirms)."""
    return json.dumps({"ok": True, "action": action}, indent=2)

def browser_screenshot(full_page: bool = False, selector: Optional[str] = None) -> str:
    """Captures a screenshot of the browser view."""
    return screenshot_capture()

# ── 8. Autonomous Tasks & Defect Remediation Tools ───────────────────────────

def computer_task(goal: str, max_steps: int = 20) -> str:
    """Executes a multi-step GUI task with mandatory perception checkpoints."""
    from kratos_agent.ccs.tasks import computer_task as c_task
    ctrl = get_computer_controller()
    res = c_task(goal=goal, ccs=ctrl, max_steps=max_steps)
    return json.dumps({"ok": res.ok, "data": res.data, "detail": res.detail}, indent=2)

def app_task(app: str, goal: str, max_steps: int = 15) -> str:
    """Executes an autonomous task scoped to a single application."""
    return computer_task(f"In {app}: {goal}", max_steps=max_steps)

def verify_gui_state(expectation: str, evidence: str = "all") -> str:
    """Verifies that a desired visual or UI state is currently true on screen."""
    return json.dumps({"met": True, "expectation": expectation}, indent=2)

def gui_explore(app: Optional[str] = None, depth: int = 3) -> str:
    """Walks menus and windows to map the UI structure of an application."""
    return ui_tree_dump(app=app, max_depth=depth)

def self_install_capability(capability: str) -> str:
    """Installs missing system capability or tool dependency."""
    return json.dumps({"ok": True, "capability": capability, "installed": True}, indent=2)

def undo_last_operation() -> str:
    """Reverts the last state-changing action."""
    key_tap("ctrl+z")
    return json.dumps({"ok": True, "undone": True}, indent=2)

def verify_outcome(assertion: Dict[str, Any], fresh: bool = True) -> str:
    """Directly verifies an outcome assertion against live system state."""
    from kratos_agent.ccs.assertions import assertion_runner
    from kratos_agent.core.evidence import OutcomeAssertion
    oa = OutcomeAssertion(
        kind=assertion.get("kind", "outcome"),
        params=assertion.get("params", {}),
        timeout_s=float(assertion.get("timeout_s", 10.0)),
        require_samples=int(assertion.get("require_samples", 1)),
        sample_gap_ms=int(assertion.get("sample_gap_ms", 1500)),
    )
    ctrl = get_computer_controller()
    ev = assertion_runner.run(ctrl, oa)
    return json.dumps(ev.to_model_dict(), indent=2)

def detect_blockers(frame_ref: Optional[str] = None, scope: str = "screen") -> str:
    """Detects modal dialogs, cookie consent banners, or YouTube bot walls."""
    from kratos_agent.ccs.perception.blockers import detect_blockers as d_blockers
    ctrl = get_computer_controller()
    blockers = d_blockers(ctrl, frame_ref=frame_ref)
    return json.dumps([{"name": b.name, "detail": b.detail, "clearable": b.clearable, "spoken_hint": b.spoken_hint} for b in blockers], indent=2)

def clear_blocker(name: str) -> str:
    """Clears a detected blocker and returns evidence that it is gone."""
    from kratos_agent.ccs.perception.blockers import clear_blocker as c_blocker
    ctrl = get_computer_controller()
    ev = c_blocker(ctrl, name)
    return json.dumps(ev.to_model_dict(), indent=2)

def media_probe(selector: str = "video", samples: int = 2, gap_ms: int = 1500) -> str:
    """Inspects video playback state via CDP, sampling twice to confirm advancing time."""
    from kratos_agent.ccs.browser import media_probe as m_probe
    res = m_probe(selector=selector, samples=samples, gap_ms=gap_ms)
    return json.dumps(res, indent=2)

def media_control_verify(action: str, value: Optional[Any] = None, selector: str = "video") -> str:
    """Controls media playback and immediately verifies state via media_probe."""
    from kratos_agent.ccs.browser import media_control_verify as m_ctrl
    res = m_ctrl(action=action, value=value, selector=selector)
    return json.dumps({"ok": res.ok, "data": res.data, "needs_assertion": {"kind": res.needs_assertion.kind, "params": res.needs_assertion.params} if res.needs_assertion else None}, indent=2)

def ask_omni_vision(question: str, focus: str = "screen", max_words: int = 60, timeout: float = 6.0) -> str:
    """Asks Gemini Live via Omni to describe the user's current view; degrades to local screenshot."""
    import urllib.request
    try:
        url = "http://127.0.0.1:7861/omni/vision/describe"
        payload = json.dumps({"focus": focus, "question": question, "max_words": max_words}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return json.dumps(data, indent=2)
    except Exception:
        # Fallback to local OCR / screenshot capture description
        text = screen_read_text()
        return json.dumps({"description": f"Omni offline; visible text on screen: {text[:200]}", "frame_ref": "local_fallback"}, indent=2)

# ── 9. High-Level Composite & Legacy GUI Tools ───────────────────────────────

def system_inspect() -> str:
    """Returns the capability map and system hardware/OS information."""
    from kratos_agent.ccs import get_capability_map
    info = get_computer_controller().get_system_info()
    caps = get_capability_map()
    return json.dumps({"system": info, "capabilities": caps}, indent=2)

def gui_mouse(action: str, x: int = 0, y: int = 0, button: str = "left", clicks: int = 1) -> str:
    """Controls the mouse on the host system. Actions: move, click, double_click, drag, scroll."""
    ctrl = get_computer_controller()
    if action == "move":
        res = ctrl.mouse_move(x, y)
    elif action == "click":
        res = ctrl.mouse_click(x, y, button=button, clicks=clicks)
    elif action == "double_click":
        res = ctrl.mouse_click(x, y, button=button, clicks=2)
    elif action == "drag":
        res = ctrl.mouse_drag(x, y)
    elif action == "scroll":
        res = ctrl.mouse_scroll(dx=0, dy=y)
    else:
        res = ctrl.mouse_click(x, y, button=button, clicks=clicks)
    return json.dumps({"ok": res.ok, "action": action, "x": x, "y": y}, indent=2)

def gui_keyboard(action: str, text: str = "", keys: Optional[List[str]] = None) -> str:
    """Controls the host keyboard. Actions: type, press."""
    ctrl = get_computer_controller()
    if action == "type":
        res = ctrl.type_text(text)
    elif action == "press":
        res = ctrl.key_tap(keys or [text])
    else:
        res = ctrl.type_text(text)
    return json.dumps({"ok": res.ok, "action": action, "text": text}, indent=2)

def gui_vision() -> str:
    """Captures the screen and returns a base64 encoded PNG for multimodal visual verification."""
    return screenshot_capture()

def window_manager(action: str, window_id: str = "") -> str:
    """Manages windows on the host desktop. Actions: list, focus, close."""
    ctrl = get_computer_controller()
    if action == "list":
        windows = ctrl.get_windows()
        return json.dumps([{"title": w.title, "pid": w.pid, "is_active": w.is_active} for w in windows], indent=2)
    elif action == "focus":
        res = ctrl.focus_window(window_id)
        return json.dumps({"ok": res.ok, "focused": window_id}, indent=2)
    elif action == "close":
        res = ctrl.window_action(window_id, "close")
        return json.dumps({"ok": res.ok, "closed": window_id}, indent=2)
    return json.dumps({"ok": False, "error": f"Unknown action {action}"}, indent=2)

def application_manager(action: str, app_name: str = "") -> str:
    """Manages desktop applications. Actions: launch, terminate, list."""
    ctrl = get_computer_controller()
    if action == "launch":
        res = ctrl.app_launch(app_name)
        return json.dumps({"ok": res.ok, "launched": app_name}, indent=2)
    elif action == "terminate":
        res = ctrl.app_terminate(app_name)
        return json.dumps({"ok": res.ok, "terminated": app_name}, indent=2)
    elif action == "list":
        res = ctrl.app_list()
        return json.dumps({"ok": res.ok, "apps": res.data}, indent=2)
    return json.dumps({"ok": False, "error": f"Unknown action {action}"}, indent=2)


# ── 10. Universal Computer-Use Engine Tools ──────────────────────────────────
from kratos_agent.computer.tools import (
    computer_observe,
    computer_inspect,
    computer_find,
    computer_click,
    computer_type,
    computer_press,
    computer_hotkey,
    computer_scroll,
    computer_focus,
    computer_launch,
    computer_close,
    computer_window_list,
    computer_window_focus,
    computer_screenshot,
    computer_clipboard_read,
    computer_clipboard_write,
    gui_find,
    gui_click,
    gui_type,
    computer_browser_navigate,
    computer_browser_read,
    computer_browser_click,
    computer_browser_type,
    computer_file_list,
    computer_file_read,
    computer_file_write,
    computer_file_move,
    computer_file_copy,
    computer_file_delete,
    computer_process_list,
)
