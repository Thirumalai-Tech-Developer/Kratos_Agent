from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests

POSSIBLE_CREDS_PATHS = [
    Path(os.environ.get("KRATOS_CREDS_FILE", "")) if os.environ.get("KRATOS_CREDS_FILE") else Path.cwd() / "creds.json",
    Path.cwd() / "creds.json",
    Path.home() / ".config" / "antigravity" / "creds.json",
    Path.home() / ".antigravity" / "creds.json",
    Path(__file__).resolve().parent.parent.parent.parent / "creds.json",
]

class GeminiKeyPool:
    """Manages pool of official Gemini API keys loaded from creds.json or environment."""
    def __init__(self, creds_path: Optional[Path] = None):
        self.creds_path = creds_path or self._find_creds_path()
        self.api_keys: List[Dict[str, str]] = []
        self._current_index = 0
        self.load_keys()

    def _find_creds_path(self) -> Optional[Path]:
        for p in POSSIBLE_CREDS_PATHS:
            if p and p.exists() and p.is_file():
                return p
        return None

    def load_keys(self) -> None:
        self.api_keys = []
        
        # 1. Load from environment
        env_key = os.getenv("GEMINI_API_KEY")
        if env_key:
            self.api_keys.append({"name": "ENV_KEY", "key": env_key})

        # 2. Load from creds.json
        if self.creds_path and self.creds_path.exists():
            try:
                data = json.loads(self.creds_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for item in data:
                        if item.get("provider") == "gemini" and item.get("apiKey"):
                            self.api_keys.append({
                                "name": item.get("name", f"Key {len(self.api_keys)+1}"),
                                "key": item["apiKey"]
                            })
            except Exception:
                pass

    def get_key(self) -> Optional[str]:
        if not self.api_keys:
            return None
        self._current_index = self._current_index % len(self.api_keys)
        return self.api_keys[self._current_index]["key"]

    def rotate(self) -> None:
        if self.api_keys:
            self._current_index = (self._current_index + 1) % len(self.api_keys)

    def _map_model_name(self, model: str) -> str:
        model_lower = (model or "").lower()
        if "pro" in model_lower:
            return "gemini-2.5-pro"
        return "gemini-2.5-flash"

    def generate(
        self,
        model: str,
        contents: List[Dict[str, Any]],
        system_instruction: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Calls Google Generative Language API directly with function calling & automatic key rotation.
        Returns {"content": str, "tool_calls": List[Dict[str, Any]]}.
        """
        if not self.api_keys:
            raise RuntimeError("No Gemini API keys found in creds.json or GEMINI_API_KEY environment variable.")

        target_model = self._map_model_name(model)

        # Format function declarations if tools are provided
        google_tools = []
        if tools:
            declarations = []
            for t in tools:
                fn = t.get("function", t) if isinstance(t, dict) else t
                name = fn.get("name")
                if not name:
                    continue
                declarations.append({
                    "name": name,
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters", {"type": "object", "properties": {}})
                })
            if declarations:
                google_tools.append({"function_declarations": declarations})

        payload: Dict[str, Any] = {"contents": contents}
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
        if google_tools:
            payload["tools"] = google_tools

        attempts = 0
        max_attempts = len(self.api_keys) * 2

        while attempts < max_attempts:
            attempts += 1
            key = self.get_key()
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{target_model}:generateContent?key={key}"

            try:
                resp = requests.post(url, json=payload, timeout=45)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        text_chunks = []
                        tool_calls = []
                        for p in parts:
                            if "text" in p and p["text"]:
                                text_chunks.append(p["text"])
                            elif "functionCall" in p:
                                fc = p["functionCall"]
                                tool_calls.append({
                                    "name": fc.get("name", ""),
                                    "args": fc.get("args", {}),
                                    "id": f"call_{uuid.uuid4().hex[:8]}"
                                })
                        return {
                            "content": "".join(text_chunks).strip(),
                            "tool_calls": tool_calls
                        }
                    return {"content": "", "tool_calls": []}
                elif resp.status_code in (429, 403, 401):
                    self.rotate()
                    continue
                else:
                    self.rotate()
                    continue
            except Exception:
                self.rotate()
                continue

        raise RuntimeError("All Gemini API keys exhausted or rate-limited.")
