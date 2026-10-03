"""Local Studio provider checks. Credentials stay in memory and never enter output."""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import pathlib
import random
import time
import urllib.error
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["status", "free", "probe", "import"])
    parser.add_argument("--port", type=int, default=20228)
    parser.add_argument("--model", action="append", default=[])
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--show-answer", action="store_true", help="Show only the generated arithmetic answer")
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()
    root = pathlib.Path(__file__).resolve().parents[1]
    secrets = json.loads((root / ".kratos/studio/gateway/studio-secrets.json").read_text())
    base = f"http://127.0.0.1:{args.port}"
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar))

    def call(path: str, payload=None, method=None, inference=False, timeout=55):
        headers = {"Content-Type": "application/json", "Origin": base}
        if inference:
            headers["Authorization"] = "Bearer " + secrets["KRATOS_GATEWAY_API_KEY"]
        request = urllib.request.Request(base + path, data=None if payload is None else json.dumps(payload).encode(), headers=headers, method=method)
        try:
            with opener.open(request, timeout=timeout) as response:
                if "text/event-stream" in response.headers.get("Content-Type", ""):
                    deadline = time.monotonic() + timeout
                    chunks = bytearray()
                    while time.monotonic() < deadline and len(chunks) < 1_000_000:
                        chunk = response.read1(8192)
                        if not chunk:
                            break
                        chunks.extend(chunk)
                        if b"data: [DONE]" in chunks:
                            break
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Streaming diagnostic exceeded its wall-clock budget")
                    raw = chunks.decode("utf-8")
                else:
                    raw = response.read().decode("utf-8")
                return response.status, raw
        except urllib.error.HTTPError as exc:
            # Do not print upstream errors: they can contain request URLs or credentials.
            return exc.code, exc.read().decode("utf-8", errors="replace")

    connections = []
    if args.action != "probe":
        status, _ = call("/api/auth/login", {"password": secrets["INITIAL_PASSWORD"]})
        if status != 200:
            print(json.dumps({"management_login": status}))
            return
        status, raw = call("/api/providers")
        if status != 200:
            print(json.dumps({"provider_list": status}))
            return
        payload = json.loads(raw)
        connections = payload if isinstance(payload, list) else payload.get("connections", payload.get("providers", []))
    if args.action == "import":
        bridge = root / ".kratos/provider-setup/import-once.json"
        try:
            status, raw = call("/api/settings")
            settings = json.loads(raw)
            settings = settings.get("settings", settings)
            if status != 200 or settings.get("cloudEnabled") is True:
                print(json.dumps({"import": "blocked", "reason": "local-only storage must be confirmed", "cloud_enabled": settings.get("cloudEnabled")}))
                return
            entries = json.loads(bridge.read_text(encoding="utf-8"))["entries"]
            existing = {c.get("provider") for c in connections}
            for entry in entries:
                provider = entry["provider"]
                if provider in existing:
                    print(json.dumps({"provider": provider, "import": "already configured"}))
                    continue
                status, raw = call("/api/providers/bulk-web-session", {"provider": provider, "entries": [{"name": "Browser session", "credential": entry["credential"]}], "priority": 1}, "POST")
                result = json.loads(raw)
                print(json.dumps({"provider": provider, "http": status, "imported": result.get("success", 0), "failed": result.get("failed", 0)}))
        finally:
            bridge.unlink(missing_ok=True)
        return
    if args.action == "status":
        print(json.dumps({"connections": [{"id": c.get("id"), "provider": c.get("provider"), "active": c.get("isActive"), "status": c.get("testStatus")} for c in connections]}))
        return
    if args.action == "free":
        status, raw = call("/api/settings")
        if status != 200:
            print(json.dumps({"settings": status}))
            return
        settings = json.loads(raw)
        settings = settings.get("settings", settings)
        # Only enable public general-purpose providers. Preserve unrelated disabled entries.
        public_ids = {"opencode", "oc", "duckduckgo-web", "ddgw", "cloudflare-playground", "cfp", "uncloseai", "unc", "aihorde", "horde", "veoaifree-web", "veo-free"}
        blocked = settings.get("blockedProviders", [])
        updated = [p for p in blocked if p not in public_ids]
        if updated != blocked:
            result, _ = call("/api/settings", {"blockedProviders": updated}, "PATCH")
            print(json.dumps({"public_provider_enable": result}))
        existing = {c.get("provider") for c in connections}
        for connection in connections:
            if connection.get("provider") == "opencode" and not connection.get("isActive"):
                result, _ = call("/api/providers/" + connection["id"], {"isActive": True}, "PUT")
                print(json.dumps({"provider": "opencode", "enable_status": result}))
        for provider, key in [("llm7", "unused"), ("dahl", None)]:
            if provider in existing:
                print(json.dumps({"provider": provider, "setup": "already configured"}))
                continue
            if provider == "dahl":
                result, token_body = call("/api/dahl/tokens", {}, "POST")
                if result not in (200, 201):
                    print(json.dumps({"provider": provider, "token_status": result}))
                    continue
                key = json.loads(token_body).get("token")
                if not key:
                    print(json.dumps({"provider": provider, "token_status": "empty"}))
                    continue
            body = {"provider": provider, "name": "Free access", "priority": 1}
            if key is not None:
                body["apiKey"] = key
            result, _ = call("/api/providers", body)
            print(json.dumps({"provider": provider, "create_status": result}))
        return
    for model in args.model:
        left, right = random.randint(1000, 9999), random.randint(1000, 9999)
        expected = str(left + right)
        try:
            status, raw = call("/v1/chat/completions", {"model": model, "messages": [{"role": "user", "content": f"Calculate {left}+{right}, and reply with the result only."}], "max_tokens": args.max_tokens, "stream": args.stream}, inference=True, timeout=args.timeout)
            errors = False
            error_code = None
            answer = ""
            if args.stream:
                for line in raw.splitlines():
                    if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                        continue
                    try:
                        frame = json.loads(line[5:])
                    except json.JSONDecodeError:
                        continue
                    errors = errors or bool(frame.get("error"))
                    if isinstance(frame.get("error"), dict):
                        error_code = frame["error"].get("code")
                    for choice in frame.get("choices", []):
                        answer += choice.get("delta", {}).get("content") or ""
            else:
                try:
                    response = json.loads(raw)
                except json.JSONDecodeError:
                    print(json.dumps({"model": model, "http": status, "body_format": "non-json", "body_bytes": len(raw)}), flush=True)
                    continue
                errors = bool(response.get("error"))
                if isinstance(response.get("error"), dict):
                    error_code = response["error"].get("code")
                answer = ((response.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            result = {"model": model, "http": status, "stream": args.stream, "nonempty": bool(answer.strip()), "correct": answer.strip().strip("*` ") == expected, "error": errors, "error_code": error_code}
            if args.show_answer:
                result.update(answer=answer[:500], expected=expected)
            print(json.dumps(result), flush=True)
        except (OSError, ValueError) as exc:
            print(json.dumps({"model": model, "stream": args.stream, "error_type": type(exc).__name__}))


if __name__ == "__main__":
    main()
