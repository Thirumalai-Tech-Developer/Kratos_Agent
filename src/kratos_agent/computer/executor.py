"""Action executor enforcing the interaction priority ladder."""
from __future__ import annotations
import time
from typing import Any, Dict, Optional

from dataclasses import dataclass, field
from kratos_agent.computer.state import ComputerAction, ActionResult
from kratos_agent.computer.gui.resolver import get_resolver
from kratos_agent.computer.gui.input.keyboard import KeyboardEngine
from kratos_agent.computer.gui.input.mouse import MouseEngine
from kratos_agent.computer.browser.manager import get_browser_manager
from kratos_agent.computer.apps.launcher import get_launcher
from kratos_agent.computer.apps.windows import get_window_manager
from kratos_agent.computer.apps.adapters import find_adapter
from kratos_agent.computer.apps.focus import get_active_window
from kratos_agent.computer.vision.grounding import get_vision_grounding
from kratos_agent.computer.recovery import get_recovery_engine
from kratos_agent.computer.permissions import get_permission_policy
from kratos_agent.core.errors import KratosError, create_kratos_error


@dataclass
class ExecutionOutcome:
    """Standardized execution outcome contract (§29, §30)."""
    success: bool
    verified: bool = False
    error: Optional[KratosError] = None
    evidence: Dict[str, Any] = field(default_factory=dict)
    detail: str = ""

    @classmethod
    def from_action_result(cls, res: ActionResult, subsystem: str = "computer", operation: str = "action") -> ExecutionOutcome:
        err = None
        if not res.ok:
            err = create_kratos_error(
                exc=res.detail or "Action execution failed",
                subsystem=subsystem,
                operation=operation,
                details=res.data or {},
            )
        return cls(
            success=bool(res.ok and res.verified),
            verified=bool(res.verified),
            error=err,
            evidence=res.data or {},
            detail=res.detail or "",
        )



import threading

gui_action_lock = threading.Lock()


class ActionExecutor:
    """Dispatches computer actions along the strict priority ladder:
    
    1. Native application API
    2. Accessibility API
    3. Browser DOM
    4. Semantic UI element
    5. Keyboard navigation
    6. Application-specific automation
    7. Vision
    8. Coordinate mouse
    """

    def __init__(self) -> None:
        self._keyboard = KeyboardEngine()
        self._mouse = MouseEngine()

    def execute(self, action: ComputerAction) -> ActionResult:
        """Executes a computer action with permission checking, GUI lock, and automated multi-tier recovery (§33)."""
        # 1. Permission check
        permitted, reason = get_permission_policy().check_permission(action)
        if not permitted:
            return ActionResult(ok=False, action=action.action, detail=reason)

        started = time.time()

        # 2. Acquire GUI action lock so concurrent tasks don't fight over focus (§33)
        with gui_action_lock:
            # Dispatch through recovery engine
            def _dispatch_attempt(act: ComputerAction, attempt: int) -> ActionResult:
                return self._dispatch(act, attempt)

            result = get_recovery_engine().execute_with_recovery(action, _dispatch_attempt)
            result.duration_ms = int((time.time() - started) * 1000)
            return result


    def execute_outcome(self, action: ComputerAction) -> ExecutionOutcome:
        """Executes computer action and returns verified ExecutionOutcome (§29, §30)."""
        res = self.execute(action)
        return ExecutionOutcome.from_action_result(
            res,
            subsystem="browser" if "browser" in action.action.lower() else "computer",
            operation=action.action,
        )


    def _dispatch(self, action: ComputerAction, tier: int) -> ActionResult:
        act_name = action.action.lower()
        target = action.target or {}
        params = action.parameters

        # ── App & Window Management ──
        if act_name in ("launch", "app_launch"):
            return get_launcher().launch(
                target=params.get("target") or target.get("name", ""),
                args=params.get("args"),
                elevated=params.get("elevated", False),
            )
        elif act_name in ("window_focus", "focus"):
            return get_window_manager().focus_window(
                handle=params.get("handle") or target.get("id"),
                title_regex=params.get("title_regex") or target.get("name"),
            )
        elif act_name in ("window_action", "window_close"):
            return get_window_manager().window_action(
                handle=params.get("handle") or target.get("id", ""),
                action=params.get("action", "close" if "close" in act_name else "restore"),
            )

        # ── Browser Operations ──
        if act_name.startswith("browser_"):
            sub_act = act_name.replace("browser_", "")
            bm = get_browser_manager()
            if sub_act == "navigate":
                return bm.navigate(action=params.get("action", "goto"), url=params.get("url"))
            elif sub_act in ("click", "fill"):
                from kratos_agent.computer.browser.playwright import PlaywrightDriver
                drv = PlaywrightDriver()
                if sub_act == "click":
                    return drv.click(role=target.get("role"), name=target.get("name"), selector=params.get("selector"))
                else:
                    return drv.fill(text=params.get("text", ""), role=target.get("role"), name=target.get("name"), selector=params.get("selector"))

        # ── Direct Keyboard Actions ──
        if act_name in ("press", "key_tap"):
            keys = params.get("keys") or [params.get("key", "enter")]
            return self._keyboard.key_tap(keys)
        elif act_name in ("hotkey",):
            keys = params.get("keys") or [params.get("key", "")]
            return self._keyboard.key_tap(keys)
        elif act_name in ("type", "type_text") and not target:
            return self._keyboard.type_text(params.get("text", ""), interval_ms=params.get("interval_ms", 0))

        # ── Target-Directed Actions (Click / Type) ──
        # Execute along priority tiers:
        if act_name in ("click", "type"):
            # Tier 1 & 2 & 3 & 4: Semantic resolution (UIA / DOM / Semantic Element)
            if tier <= 2:
                element = get_resolver().resolve(target)
                if act_name == "click":
                    # Try native invoke / click
                    if element.backend == "windows_uia":
                        from kratos_agent.computer.gui.backends.windows_uia import WindowsUIABackend
                        return WindowsUIABackend().click_element(element, button=params.get("button", "left"))
                    elif element.backend == "playwright":
                        from kratos_agent.computer.gui.backends.playwright import PlaywrightBackend
                        return PlaywrightBackend().click_element(element, button=params.get("button", "left"))
                    elif element.center:
                        return self._mouse.click(x=element.center.x, y=element.center.y, button=params.get("button", "left"))
                else:
                    # Type into element
                    if element.backend == "windows_uia":
                        from kratos_agent.computer.gui.backends.windows_uia import WindowsUIABackend
                        return WindowsUIABackend().type_element(element, text=params.get("text", ""))
                    elif element.backend == "playwright":
                        from kratos_agent.computer.gui.backends.playwright import PlaywrightBackend
                        return PlaywrightBackend().type_element(element, text=params.get("text", ""))
                    elif element.center:
                        self._mouse.click(x=element.center.x, y=element.center.y)
                        return self._keyboard.type_text(params.get("text", ""))

            # Tier 3: Keyboard navigation
            elif tier == 3:
                # If target is submit/ok/cancel, keyboard Enter/Escape can often fulfill it
                t_name = (target.get("name") or "").lower()
                if t_name in ("ok", "submit", "enter", "yes", "save"):
                    return self._keyboard.press("enter")
                elif t_name in ("cancel", "no", "close"):
                    return self._keyboard.press("escape")

            # Tier 4: Application Adapter
            elif tier == 4:
                active_win = get_active_window()
                if active_win:
                    adapter = find_adapter(active_win.title, active_win.app_name)
                    if adapter:
                        shortcuts = adapter.get_shortcuts()
                        t_name = (target.get("name") or "").lower().replace(" ", "_")
                        for action_key, shortcut in shortcuts.items():
                            if t_name in action_key or action_key in t_name:
                                return self._keyboard.key_tap(shortcut.split("+"))

            # Tier 5: Vision Grounding
            elif tier == 5:
                q = target.get("name") or target.get("text") or ""
                if q:
                    v_elem = get_vision_grounding().find_visual_target(q)
                    if v_elem and v_elem.center:
                        if act_name == "click":
                            return self._mouse.click(x=v_elem.center.x, y=v_elem.center.y, button=params.get("button", "left"))
                        else:
                            self._mouse.click(x=v_elem.center.x, y=v_elem.center.y)
                            return self._keyboard.type_text(params.get("text", ""))

            # Tier 6: Coordinate fallback (only if coordinates explicitly present in target or params)
            elif tier == 6:
                x = params.get("x") or (target.get("center") or {}).get("x")
                y = params.get("y") or (target.get("center") or {}).get("y")
                if x is not None and y is not None:
                    if act_name == "click":
                        return self._mouse.click(x=x, y=y, button=params.get("button", "left"))
                    else:
                        self._mouse.click(x=x, y=y)
                        return self._keyboard.type_text(params.get("text", ""))

        return ActionResult(ok=False, action=action.action, detail=f"Action could not be executed at tier {tier}")


_executor: Optional[ActionExecutor] = None


def get_executor() -> ActionExecutor:
    global _executor
    if _executor is None:
        _executor = ActionExecutor()
    return _executor
