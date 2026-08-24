from __future__ import annotations

import json
import os
import time
import sys
from typing import Any, Dict, Iterator, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from kratos_agent.antigravity.accounts import (
    Account,
    AccountPool,
    content_headers,
    discover_project,
    refresh_access_token,
    AntigravityAuthError,
    PUBLIC_MODELS
)

STREAM_GENERATE_PATH = "/v1internal:streamGenerateContent?alt=sse"
RUNTIME_BASE_URLS = [
    "https://daily-cloudcode-pa.googleapis.com",
    "https://cloudcode-pa.googleapis.com",
]

class AntigravityClient:
    """In-process Google Cloud Code SSE client with multi-account rotation."""
    def __init__(self, pool: Optional[AccountPool] = None):
        self.pool = pool or AccountPool()

    def _format_messages_to_prompt(self, messages: List[Dict[str, Any]], system_instruction: Optional[str] = None) -> str:
        parts = []
        if system_instruction:
            parts.append(f"[System Instruction]: {system_instruction}")

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and "text" in p]
                content = " ".join(text_parts)

            if role in ("system", "developer"):
                parts.append(f"[System]: {content}")
            elif role == "user":
                parts.append(f"[User]: {content}")
            elif role == "assistant":
                parts.append(f"[Assistant]: {content}")

        return "\n\n".join(parts)

    def generate(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        system_instruction: Optional[str] = None,
        max_retries: int = 10
    ) -> str:
        """Executes generation with direct HTTP streaming over cloudcode-pa."""
        chunks = list(self.stream(model, messages, system_instruction, max_retries))
        text = "".join(chunks).strip()
        if text:
            return text
        raise RuntimeError(f"Generation returned empty response for model {model}")

    def build_envelope(
        self,
        account: Account,
        model: str,
        messages: List[Dict[str, Any]],
        system_instruction: Optional[str] = None
    ) -> Dict[str, Any]:
        contents = []
        sys_parts = []

        if system_instruction:
            sys_parts.append({"text": system_instruction})

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role in ("system", "developer"):
                if isinstance(content, str) and content:
                    sys_parts.append({"text": content})
            elif role == "user":
                if isinstance(content, str):
                    contents.append({"role": "user", "parts": [{"text": content}]})
                elif isinstance(content, list):
                    parts = []
                    for p in content:
                        if isinstance(p, dict) and "text" in p:
                            parts.append({"text": p["text"]})
                        elif isinstance(p, str):
                            parts.append({"text": p})
                    contents.append({"role": "user", "parts": parts or [{"text": " "}]})
            elif role == "assistant":
                text = content if isinstance(content, str) else str(content)
                contents.append({"role": "model", "parts": [{"text": text or " "}]})

        request_body: Dict[str, Any] = {
            "contents": contents or [{"role": "user", "parts": [{"text": " "}]}]
        }
        if sys_parts:
            request_body["systemInstruction"] = {"parts": sys_parts}

        return {
            "project": account.project_id or "trusty-processor-5txfk",
            "model": model,
            "request": request_body
        }

    def stream(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        system_instruction: Optional[str] = None,
        max_retries: int = 10
    ) -> Iterator[str]:
        attempt = 0
        last_error = None

        while attempt < max_retries:
            attempt += 1
            account = self.pool.get_active_account()
            if not account:
                break

            try:
                self.pool.ensure_ready(account)
            except Exception as e:
                self.pool.mark_cooldown(account.name, duration_seconds=120)
                last_error = e
                continue

            envelope = self.build_envelope(account, model, messages, system_instruction)
            headers = content_headers(account)
            body_bytes = json.dumps(envelope).encode("utf-8")

            success = False
            for base in RUNTIME_BASE_URLS:
                url = f"{base}{STREAM_GENERATE_PATH}"
                req = Request(url, data=body_bytes, headers=headers, method="POST")

                try:
                    with urlopen(req, timeout=90) as resp:
                        for line in resp:
                            line_str = line.decode("utf-8", errors="replace").strip()
                            if not line_str.startswith("data:"):
                                continue
                            payload_str = line_str[5:].strip()
                            if not payload_str or payload_str == "[DONE]":
                                continue

                            try:
                                data = json.loads(payload_str)
                            except Exception:
                                continue

                            response_obj = data.get("response", {})
                            candidates = response_obj.get("candidates", [])
                            for cand in candidates:
                                parts = cand.get("content", {}).get("parts", [])
                                for p in parts:
                                    if not p.get("thought") and "text" in p and p["text"]:
                                        yield p["text"]
                                if cand.get("finishReason") == "MALFORMED_FUNCTION_CALL" and cand.get("finishMessage"):
                                    yield cand["finishMessage"]
                        success = True
                        break

                except HTTPError as exc:
                    raw = exc.read().decode("utf-8", errors="replace")
                    if exc.code == 401:
                        try:
                            refresh_access_token(account)
                            headers = content_headers(account)
                        except Exception:
                            self.pool.mark_cooldown(account.name, duration_seconds=300)
                            break
                    elif exc.code in (429, 503, 500):
                        last_error = f"Account {account.name} received HTTP {exc.code} from {base}: {raw[:200]}"
                        continue
                    else:
                        last_error = f"HTTP {exc.code} from {url}: {raw[:300]}"
                        continue
                except URLError as exc:
                    last_error = f"Network error: {exc}"
                    continue
                except Exception as exc:
                    last_error = exc
                    continue

            if success:
                return

        raise RuntimeError(f"Antigravity generation failed after {max_retries} attempts. Last error: {last_error}")
