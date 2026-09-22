"""Playwright browser automation driver with CDP fallback."""
from __future__ import annotations
import json
import time
from typing import Any, Dict, List, Optional

from kratos_agent.ccs.browser.cdp import cdp_client
from kratos_agent.computer.state import ActionResult


class PlaywrightDriver:
    """Semantic browser driver preferring role-based DOM interactions."""

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._initialized = False

    def is_available(self) -> bool:
        # Returns True if Playwright library is importable OR CDP is connected
        if cdp_client.is_available():
            return True
        try:
            import playwright  # noqa: F401
            return True
        except ImportError:
            return False

    def click(self, role: Optional[str] = None, name: Optional[str] = None, selector: Optional[str] = None) -> ActionResult:
        """Clicks an element using semantic role/name or CSS selector."""
        if cdp_client.is_available():
            if selector:
                success = cdp_client.click(selector)
                return ActionResult(ok=success, action="browser_click", data={"selector": selector}, method_used="cdp_selector")
            elif role or name:
                # Semantic DOM click via JS in CDP
                js = f"""(() => {{
                    const role = "{role or ''}".toLowerCase();
                    const name = "{name or ''}".toLowerCase();
                    const candidates = Array.from(document.querySelectorAll('button, a, input[type=button], input[type=submit], [role]'));
                    for (const el of candidates) {{
                        const elRole = (el.getAttribute('role') || el.tagName).toLowerCase();
                        const elText = (el.innerText || el.value || el.getAttribute('aria-label') || '').toLowerCase();
                        if ((!role || elRole.includes(role)) && (!name || elText.includes(name))) {{
                            el.click();
                            return true;
                        }}
                    }}
                    return false;
                }})()"""
                res = cdp_client.evaluate(js)
                return ActionResult(ok=bool(res), action="browser_click", data={"role": role, "name": name}, method_used="cdp_semantic_dom")

        return ActionResult(ok=False, action="browser_click", detail="Browser not connected")

    def fill(self, text: str, role: Optional[str] = None, name: Optional[str] = None, selector: Optional[str] = None) -> ActionResult:
        """Fills an input or textarea element."""
        if cdp_client.is_available():
            clean_text = text.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
            if selector:
                js = f"""(() => {{
                    const el = document.querySelector('{selector}');
                    if (el) {{
                        el.value = '{clean_text}';
                        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        return true;
                    }}
                    return false;
                }})()"""
            else:
                js = f"""(() => {{
                    const name = "{name or ''}".toLowerCase();
                    const inputs = Array.from(document.querySelectorAll('input, textarea'));
                    for (const el of inputs) {{
                        const label = (el.placeholder || el.name || el.getAttribute('aria-label') || el.id || '').toLowerCase();
                        if (!name || label.includes(name)) {{
                            el.focus();
                            el.value = '{clean_text}';
                            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            return true;
                        }}
                    }}
                    return false;
                }})()"""
            res = cdp_client.evaluate(js)
            return ActionResult(ok=bool(res), action="browser_fill", data={"text": text}, method_used="cdp_dom_fill")

        return ActionResult(ok=False, action="browser_fill", detail="Browser not connected")

    def dump_interactive_dom(self) -> List[Dict[str, Any]]:
        """Dumps interactive DOM elements (buttons, inputs, links) with bounding rects."""
        if not cdp_client.is_available():
            return []

        js = """(() => {
            const elements = [];
            const interactive = document.querySelectorAll('button, a, input, select, textarea, [role=button], [role=link], [role=textbox]');
            let idCounter = 1;
            for (const el of interactive) {
                const rect = el.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).visibility !== 'hidden') {
                    elements.push({
                        id: 'dom_' + (idCounter++),
                        role: el.getAttribute('role') || el.tagName.toLowerCase(),
                        name: (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim().substring(0, 100),
                        bounds: {
                            x: Math.round(rect.left),
                            y: Math.round(rect.top),
                            w: Math.round(rect.width),
                            h: Math.round(rect.height)
                        },
                        tag: el.tagName.toLowerCase(),
                        disabled: el.disabled || false
                    });
                }
            }
            return elements;
        })()"""
        try:
            res = cdp_client.evaluate(js)
            return res if isinstance(res, list) else []
        except Exception:
            return []
