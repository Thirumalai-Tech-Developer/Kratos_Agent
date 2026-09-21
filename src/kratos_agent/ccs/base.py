import abc
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Literal, Tuple

class CapabilityUnavailable(RuntimeError):
    """Raised when a requested capability is not present on this platform/machine.
    Carries enough info for the model to work around it or self-install what's missing."""
    def __init__(self, capability: str, platform: str, hint: str = "", install: str | None = None):
        self.capability = capability
        self.platform = platform
        self.hint = hint
        self.install = install
        msg = f"{capability} unavailable on {platform}. {hint}"
        if install:
            msg += f" Install with: {install}"
        super().__init__(msg)

@dataclass
class WindowInfo:
    id: str
    title: str
    app_name: str
    is_active: bool
    bounds: Dict[str, int]  # x, y, width, height

@dataclass
class DisplayInfo:
    id: str
    is_primary: bool
    bounds: Dict[str, int]
    resolution: str

    @property
    def width(self) -> int:
        return self.bounds.get("width", 1920)

    @property
    def height(self) -> int:
        return self.bounds.get("height", 1080)

    @property
    def scale_factor(self) -> float:
        return 1.0

    @property
    def index(self) -> int:
        return 0

class ComputerController(abc.ABC):
    """Abstract base class for OS-specific computer control operations."""
    
    # ── MOUSE ──────────────────────────────────────────────
    @abc.abstractmethod
    def mouse_move(self, x: int, y: int) -> None:
        raise CapabilityUnavailable("mouse_move", "abstract", "Abstract method not implemented on base class.")
        
    @abc.abstractmethod
    def mouse_click(self, button: str = "left", double: bool = False) -> None:
        raise CapabilityUnavailable("mouse_click", "abstract", "Abstract method not implemented on base class.")
        
    @abc.abstractmethod
    def mouse_drag(self, x: int, y: int) -> None:
        raise CapabilityUnavailable("mouse_drag", "abstract", "Abstract method not implemented on base class.")
        
    @abc.abstractmethod
    def mouse_scroll(self, clicks: int) -> None:
        raise CapabilityUnavailable("mouse_scroll", "abstract", "Abstract method not implemented on base class.")

    # ── KEYBOARD ───────────────────────────────────────────
    @abc.abstractmethod
    def keyboard_type(self, text: str) -> None:
        raise CapabilityUnavailable("keyboard_type", "abstract", "Abstract method not implemented on base class.")
        
    @abc.abstractmethod
    def keyboard_press(self, keys: List[str]) -> None:
        """Presses a combination of keys (e.g. ['ctrl', 'c'])."""
        raise CapabilityUnavailable("keyboard_press", "abstract", "Abstract method not implemented on base class.")

    # ── SCREEN & VISION ────────────────────────────────────
    @abc.abstractmethod
    def take_screenshot(self, monitor_id: Optional[str] = None) -> bytes:
        """Returns screenshot as PNG bytes."""
        raise CapabilityUnavailable("take_screenshot", "abstract", "Abstract method not implemented on base class.")
        
    @abc.abstractmethod
    def get_displays(self) -> List[DisplayInfo]:
        raise CapabilityUnavailable("get_displays", "abstract", "Abstract method not implemented on base class.")

    # ── WINDOW MANAGEMENT ──────────────────────────────────
    @abc.abstractmethod
    def list_windows(self) -> List[WindowInfo]:
        raise CapabilityUnavailable("list_windows", "abstract", "Abstract method not implemented on base class.")
        
    @abc.abstractmethod
    def focus_window(self, window_id: str) -> bool:
        raise CapabilityUnavailable("focus_window", "abstract", "Abstract method not implemented on base class.")
        
    @abc.abstractmethod
    def close_window(self, window_id: str) -> bool:
        raise CapabilityUnavailable("close_window", "abstract", "Abstract method not implemented on base class.")

    # ── CLIPBOARD ──────────────────────────────────────────
    @abc.abstractmethod
    def get_clipboard(self) -> str:
        raise CapabilityUnavailable("get_clipboard", "abstract", "Abstract method not implemented on base class.")
        
    @abc.abstractmethod
    def set_clipboard(self, text: str) -> None:
        raise CapabilityUnavailable("set_clipboard", "abstract", "Abstract method not implemented on base class.")

    # ── SYSTEM CAPABILITIES ────────────────────────────────
    @abc.abstractmethod
    def get_system_info(self) -> Dict[str, Any]:
        """Returns OS version, memory, CPU info, etc."""
        raise CapabilityUnavailable("get_system_info", "abstract", "Abstract method not implemented on base class.")
        
    @abc.abstractmethod
    def list_applications(self) -> List[Dict[str, str]]:
        raise CapabilityUnavailable("list_applications", "abstract", "Abstract method not implemented on base class.")
        
    @abc.abstractmethod
    def launch_application(self, app_name_or_path: str) -> bool:
        raise CapabilityUnavailable("launch_application", "abstract", "Abstract method not implemented on base class.")

@dataclass(frozen=True)
class Point:
    x: int
    y: int

@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int
    
    @property
    def center(self) -> Point:
        return Point(self.x + self.w // 2, self.y + self.h // 2)

@dataclass
class ElementHandle:
    """A resolved UI element. Opaque `native` payload is platform-specific."""
    ref: str                       # stable short id for the model to reference ("e17")
    role: str                      # "Button", "Edit", "ListItem", "MenuItem", …
    name: str                      # accessible name / label
    value: str | None
    rect: Rect
    states: List[str]              # ["focused", "enabled", "checked", "expanded"]
    patterns: List[str]            # ["Invoke", "Value", "Toggle", "SelectionItem", "Scroll"]
    app: str                       # process name
    window: str                    # window title
    depth: int
    native: object | None = None
    
    def to_model_dict(self) -> Dict[str, Any]:
        """Compact representation for Headroom/LLM consumption."""
        d = {
            "ref": self.ref,
            "role": self.role,
            "name": self.name,
            "rect": {"x": self.rect.x, "y": self.rect.y, "w": self.rect.w, "h": self.rect.h}
        }
        if self.value is not None: d["value"] = self.value
        if self.states: d["states"] = self.states
        if self.patterns: d["patterns"] = self.patterns
        return d

@dataclass
class ActionResult:
    ok: bool
    action: str
    detail: str = ""
    data: dict | None = None
    screenshot_ref: str | None = None      # id of the post-action frame, if captured
    duration_ms: int = 0


class PlatformBackend(ABC):
    platform: str = "abstract"

    # ── perception ───────────────────────────────────────────────────────────
    @abstractmethod
    def screenshot(self, monitor: int | None = None, region: Rect | None = None,
                   include_cursor: bool = False) -> bytes:
        """Returns PNG bytes."""
        raise CapabilityUnavailable("screenshot", "abstract", "Abstract method not implemented on base class.")
        
    @abstractmethod
    def a11y_supported(self) -> bool:
        raise CapabilityUnavailable("a11y_supported", "abstract", "Abstract method not implemented on base class.")
        
    @abstractmethod
    def dump_tree(self, app: str | None = None, root_window: str | None = None,
                  max_depth: int = 12, max_nodes: int = 800,
                  visible_only: bool = True) -> List[ElementHandle]:
        raise CapabilityUnavailable("dump_tree", "abstract", "Abstract method not implemented on base class.")
        
    @abstractmethod
    def find_element(self, query: str, app: str | None = None,
                     role: str | None = None, index: int = 0) -> ElementHandle | None:
        raise CapabilityUnavailable("find_element", "abstract", "Abstract method not implemented on base class.")

    # ── input ────────────────────────────────────────────────────────────────
    @abstractmethod
    def mouse_move(self, p: Point, duration_ms: int = 0) -> ActionResult:
        raise CapabilityUnavailable("mouse_move", "abstract", "Abstract method not implemented on base class.")
        
    @abstractmethod
    def mouse_click(self, p: Point | None = None, button: str = "left",
                    clicks: int = 1, modifiers: List[str] = field(default_factory=list)) -> ActionResult:
        raise CapabilityUnavailable("mouse_click", "abstract", "Abstract method not implemented on base class.")
        
    @abstractmethod
    def mouse_drag(self, a: Point, b: Point, button: str = "left",
                   duration_ms: int = 200, steps: int = 24) -> ActionResult:
        raise CapabilityUnavailable("mouse_drag", "abstract", "Abstract method not implemented on base class.")
        
    @abstractmethod
    def mouse_scroll(self, dy: int, dx: int = 0, at: Point | None = None) -> ActionResult:
        raise CapabilityUnavailable("mouse_scroll", "abstract", "Abstract method not implemented on base class.")
        
    @abstractmethod
    def key_tap(self, keys: List[str]) -> ActionResult:
        raise CapabilityUnavailable("key_tap", "abstract", "Abstract method not implemented on base class.")
        
    @abstractmethod
    def type_text(self, text: str, interval_ms: int = 0,
                  strategy: str = "auto") -> ActionResult:
        raise CapabilityUnavailable("type_text", "abstract", "Abstract method not implemented on base class.")

    # ── windows ──────────────────────────────────────────────────────────────
    @abstractmethod
    def list_windows(self, include_minimized: bool = True) -> List[Dict[str, Any]]:
        raise CapabilityUnavailable("list_windows", "abstract", "Abstract method not implemented on base class.")
        
    @abstractmethod
    def focus_window(self, handle: str | int | None = None, title_regex: str | None = None) -> ActionResult:
        raise CapabilityUnavailable("focus_window", "abstract", "Abstract method not implemented on base class.")
        
    @abstractmethod
    def window_action(self, handle: Any, action: str, rect: Rect | None = None) -> ActionResult:
        raise CapabilityUnavailable("window_action", "abstract", "Abstract method not implemented on base class.")

    # ── system ───────────────────────────────────────────────────────────────
    @abstractmethod
    def launch(self, target: str, args: List[str] = field(default_factory=list), cwd: str | None = None,
               elevated: bool = False, verb: str | None = None,
               wait: bool = False, timeout: float | None = None) -> ActionResult:
        raise CapabilityUnavailable("launch", "abstract", "Abstract method not implemented on base class.")
        
    @abstractmethod
    def can_elevate(self) -> bool:
        raise CapabilityUnavailable("can_elevate", "abstract", "Abstract method not implemented on base class.")
        
    @abstractmethod
    def run_elevated(self, command: str, wait: bool = True,
                     timeout: float | None = None) -> ActionResult:
        raise CapabilityUnavailable("run_elevated", "abstract", "Abstract method not implemented on base class.")
        
    @abstractmethod
    def display_info(self) -> List[Dict[str, Any]]:
        raise CapabilityUnavailable("display_info", "abstract", "Abstract method not implemented on base class.")
