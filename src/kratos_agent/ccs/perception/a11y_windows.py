
import logging
logger = logging.getLogger(__name__)
import queue
import threading
from collections.abc import Callable
from typing import Any

try:
    import comtypes
    import comtypes.client
    # Generate wrapper for UIAutomationClient if not already generated
    UIAutomationClient = comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen.UIAutomationClient import *
except ImportError:
    UIAutomationClient = None

from kratos_agent.ccs.base import CapabilityUnavailable, ElementHandle, Rect


class UIAWorker:
    def __init__(self):
        if UIAutomationClient is None:
            raise CapabilityUnavailable("UIA", "Windows", "comtypes or UIAutomationCore.dll missing")
        self.q = queue.Queue()
        self.t = threading.Thread(target=self._worker, daemon=True)
        self.t.start()

    def _worker(self):
        # Must run in MTA mode
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        self.uia = comtypes.client.CreateObject(CUIAutomation, interface=IUIAutomation)
        self.tree_walker = self.uia.ControlViewWalker
        self.root = self.uia.GetRootElement()

        while True:
            func, args, kwargs, result_q = self.q.get()
            try:
                res = func(*args, **kwargs)
                result_q.put((res, None))
            except Exception as e:
                result_q.put((None, e))
            self.q.task_done()

    def submit(self, func: Callable, *args, **kwargs) -> Any:
        result_q = queue.Queue()
        self.q.put((func, args, kwargs, result_q))
        res, err = result_q.get()
        if err:
            raise err
        return res

class WindowsA11yEngine:
    def __init__(self):
        self.worker = UIAWorker()

    def dump_tree(self, max_depth: int = 12, max_nodes: int = 800) -> list[ElementHandle]:
        def _do_dump():
            elements = []
            # We skip traversing here as a full UIAutomation traversal in python can be very slow.
            # A recursive tree walker using self.worker.tree_walker is needed.
            
            def traverse(node, depth, current_id):
                if depth > max_depth or len(elements) >= max_nodes:
                    return
                if not node:
                    return
                
                try:
                    rect = node.CurrentBoundingRectangle
                    r = Rect(x=rect.left, y=rect.top, w=rect.right - rect.left, h=rect.bottom - rect.top)
                    name = node.CurrentName or ""
                    role = node.CurrentLocalizedControlType or ""
                    is_offscreen = node.CurrentIsOffscreen
                    if is_offscreen:
                        return # Skip invisible elements for now
                    
                    elements.append(ElementHandle(
                        ref=f"e{current_id[0]}",
                        role=role,
                        name=name,
                        value=None, # Implement value pattern extraction if needed
                        rect=r,
                        states=[],
                        patterns=[],
                        app="Unknown", # Requires process id lookup
                        window="Unknown",
                        depth=depth,
                        native=node
                    ))
                    current_id[0] += 1
                    
                    child = self.worker.tree_walker.GetFirstChildElement(node)
                    while child:
                        traverse(child, depth + 1, current_id)
                        child = self.worker.tree_walker.GetNextSiblingElement(child)
                except Exception as exc:
                    logger.debug("Operation error suppressed: %s", exc)

            traverse(self.worker.root, 0, [0])
            return elements

        return self.worker.submit(_do_dump)

_engine: WindowsA11yEngine | None = None

def get_a11y_engine() -> WindowsA11yEngine:
    global _engine
    if _engine is None:
        _engine = WindowsA11yEngine()
    return _engine

def dump_ui_tree(app: str | None = None, max_depth: int = 12, max_nodes: int = 800, visible_only: bool = True) -> list[ElementHandle]:
    try:
        engine = get_a11y_engine()
        return engine.dump_tree(max_depth=max_depth, max_nodes=max_nodes)
    except Exception:
        return []
