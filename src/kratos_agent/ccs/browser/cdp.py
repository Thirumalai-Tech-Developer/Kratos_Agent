"""Persistent Chrome DevTools Protocol (CDP) client.
Provides sub-150ms evaluation, navigation, and DOM/video inspection.
"""
from __future__ import annotations
import json
import urllib.request
import urllib.error
import time
from typing import Any, Dict, List, Optional

try:
    import websocket
except ImportError:
    websocket = None


class CdpClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 9222):
        self.host = host
        self.port = port
        self._ws: Optional[Any] = None
        self._ws_url: Optional[str] = None
        self._msg_id = 0

    def is_available(self) -> bool:
        try:
            url = f"http://{self.host}:{self.port}/json/version"
            req = urllib.request.Request(url, headers={"User-Agent": "Kratos/1.0"})
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _get_active_tab_ws_url(self) -> Optional[str]:
        try:
            url = f"http://{self.host}:{self.port}/json/list"
            req = urllib.request.Request(url, headers={"User-Agent": "Kratos/1.0"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for target in data:
                    if target.get("type") == "page" and "webSocketDebuggerUrl" in target:
                        return target["webSocketDebuggerUrl"]
        except Exception:
            pass
        return None

    def connect(self) -> bool:
        if not websocket:
            return False
        ws_url = self._get_active_tab_ws_url()
        if not ws_url:
            return False
        try:
            self._ws = websocket.create_connection(ws_url, timeout=3.0)
            self._ws_url = ws_url
            return True
        except Exception:
            self._ws = None
            return False

    def send_command(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self._ws:
            if not self.connect():
                return {"error": "CDP not connected"}

        self._msg_id += 1
        msg = {
            "id": self._msg_id,
            "method": method,
            "params": params or {},
        }
        try:
            self._ws.send(json.dumps(msg))
            # Read until response with matching id
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                raw = self._ws.recv()
                data = json.loads(raw)
                if data.get("id") == self._msg_id:
                    return data.get("result", {})
            return {"error": "CDP command timed out"}
        except Exception as exc:
            self._ws = None
            return {"error": str(exc)}

    def evaluate(self, expression: str, await_promise: bool = True) -> Any:
        res = self.send_command(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": await_promise,
                "returnByValue": True,
            },
        )
        if "result" in res and "value" in res["result"]:
            return res["result"]["value"]
        if "value" in res:
            return res["value"]
        return res

    def navigate(self, url: str) -> bool:
        res = self.send_command("Page.navigate", {"url": url})
        return "error" not in res

    def get_video_state(self, selector: str = "video") -> Dict[str, Any]:
        probe_js = (
            f"(() => {{"
            f"  const v = document.querySelector('{selector}');"
            f"  if (!v) return {{ found: false }};"
            f"  return {{"
            f"    found: true,"
            f"    paused: v.paused,"
            f"    ended: v.ended,"
            f"    currentTime: v.currentTime,"
            f"    duration: v.duration,"
            f"    readyState: v.readyState,"
            f"    videoWidth: v.videoWidth,"
            f"    videoHeight: v.videoHeight,"
            f"    error: v.error ? v.error.message : null,"
            f"    muted: v.muted,"
            f"    volume: v.volume"
            f"  }};"
            f"}})()"
        )
        val = self.evaluate(probe_js)
        return val if isinstance(val, dict) else {"found": False, "raw": val}

    def click(self, selector: str) -> bool:
        click_js = (
            f"(() => {{"
            f"  const el = document.querySelector('{selector}');"
            f"  if (!el) return false;"
            f"  el.click();"
            f"  return true;"
            f"}})()"
        )
        return bool(self.evaluate(click_js))

cdp_client = CdpClient()
