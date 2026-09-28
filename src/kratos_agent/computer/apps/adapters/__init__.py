"""Built-in application adapters for major desktop applications."""
from __future__ import annotations

from kratos_agent.computer.apps.adapters.base import ApplicationAdapter


class ChromeAdapter(ApplicationAdapter):
    @property
    def app_name(self) -> str:
        return "chrome"

    def matches(self, window_title: str, process_name: str) -> bool:
        t, p = window_title.lower(), process_name.lower()
        return "chrome" in t or "chrome" in p or "edge" in t or "edge" in p or "brave" in p

    def get_shortcuts(self) -> dict[str, str]:
        return {
            "focus_address_bar": "ctrl+l",
            "new_tab": "ctrl+t",
            "close_tab": "ctrl+w",
            "reopen_tab": "ctrl+shift+t",
            "refresh": "ctrl+r",
            "devtools": "f12",
            "find": "ctrl+f",
            "downloads": "ctrl+j",
            "history": "ctrl+h",
        }


class VSCodeAdapter(ApplicationAdapter):
    @property
    def app_name(self) -> str:
        return "vscode"

    def matches(self, window_title: str, process_name: str) -> bool:
        t, p = window_title.lower(), process_name.lower()
        return "visual studio code" in t or "code" in p or "cursor" in t or "cursor" in p

    def get_shortcuts(self) -> dict[str, str]:
        return {
            "command_palette": "ctrl+shift+p",
            "quick_open": "ctrl+p",
            "toggle_terminal": "ctrl+`",
            "toggle_sidebar": "ctrl+b",
            "save": "ctrl+s",
            "find": "ctrl+f",
            "find_in_files": "ctrl+shift+f",
            "format_document": "shift+alt+f",
        }


class NotepadAdapter(ApplicationAdapter):
    @property
    def app_name(self) -> str:
        return "notepad"

    def matches(self, window_title: str, process_name: str) -> bool:
        t, p = window_title.lower(), process_name.lower()
        return "notepad" in t or "notepad" in p

    def get_shortcuts(self) -> dict[str, str]:
        return {
            "save": "ctrl+s",
            "save_as": "ctrl+shift+s",
            "find": "ctrl+f",
            "replace": "ctrl+h",
            "new": "ctrl+n",
        }


class ExplorerAdapter(ApplicationAdapter):
    @property
    def app_name(self) -> str:
        return "explorer"

    def matches(self, window_title: str, process_name: str) -> bool:
        t, p = window_title.lower(), process_name.lower()
        return "file explorer" in t or "explorer" in p or "nautilus" in p or "dolphin" in p

    def get_shortcuts(self) -> dict[str, str]:
        return {
            "focus_address_bar": "alt+d",
            "search": "ctrl+f",
            "new_folder": "ctrl+shift+n",
            "refresh": "f5",
            "up_level": "alt+up",
            "rename": "f2",
        }


ADAPTERS: list[ApplicationAdapter] = [
    ChromeAdapter(),
    VSCodeAdapter(),
    NotepadAdapter(),
    ExplorerAdapter(),
]


def find_adapter(window_title: str, process_name: str = "") -> ApplicationAdapter | None:
    """Finds a matching application adapter for the given window."""
    for adapter in ADAPTERS:
        if adapter.matches(window_title, process_name):
            return adapter
    return None
