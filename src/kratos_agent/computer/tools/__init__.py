"""Unified computer tool suite exports."""
from __future__ import annotations

from kratos_agent.computer.tools.computer_tools import (
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
)
from kratos_agent.computer.tools.gui_tools import (
    gui_find,
    gui_click,
    gui_type,
)
from kratos_agent.computer.tools.browser_tools import (
    computer_browser_navigate,
    computer_browser_read,
    computer_browser_click,
    computer_browser_type,
)
from kratos_agent.computer.tools.system_tools import (
    computer_file_list,
    computer_file_read,
    computer_file_write,
    computer_file_move,
    computer_file_copy,
    computer_file_delete,
    computer_process_list,
)

__all__ = [
    "computer_observe",
    "computer_inspect",
    "computer_find",
    "computer_click",
    "computer_type",
    "computer_press",
    "computer_hotkey",
    "computer_scroll",
    "computer_focus",
    "computer_launch",
    "computer_close",
    "computer_window_list",
    "computer_window_focus",
    "computer_screenshot",
    "computer_clipboard_read",
    "computer_clipboard_write",
    "gui_find",
    "gui_click",
    "gui_type",
    "computer_browser_navigate",
    "computer_browser_read",
    "computer_browser_click",
    "computer_browser_type",
    "computer_file_list",
    "computer_file_read",
    "computer_file_write",
    "computer_file_move",
    "computer_file_copy",
    "computer_file_delete",
    "computer_process_list",
]
