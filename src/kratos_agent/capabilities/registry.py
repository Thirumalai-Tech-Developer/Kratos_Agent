from __future__ import annotations

import re
from collections.abc import Iterable
from threading import RLock

from .schema import CapabilitySpec


def _builtin_capabilities() -> Iterable[CapabilitySpec]:
    specs = [
        ("browser.navigate", "Navigate browser", "Open a URL in an existing compatible browser session.", "browser"),
        ("browser.search", "Search browser", "Search the current browser or web.", "browser"),
        ("browser.click", "Click browser target", "Click a semantic browser target.", "browser"),
        ("browser.type", "Type in browser", "Type text into a semantic browser target.", "browser"),
        ("browser.youtube.play", "Play YouTube media", "Search and play the intended YouTube video.", "media"),
        ("browser.youtube.pause", "Pause YouTube media", "Pause the current YouTube player.", "media"),
        ("browser.youtube.search", "Search YouTube", "Search YouTube without assuming a specific query.", "media"),
        ("whatsapp.open", "Open WhatsApp", "Open or focus an authenticated WhatsApp session.", "communication"),
        ("whatsapp.search_contact", "Find WhatsApp contact", "Resolve a WhatsApp contact semantically.", "communication"),
        ("whatsapp.send_message", "Send WhatsApp message", "Send a Unicode-safe message and verify it.", "communication"),
        ("app.launch", "Launch application", "Start and verify a native application.", "application"),
        ("app.close", "Close application", "Close a native application/window.", "application"),
        ("filesystem.read", "Read file", "Read a local file.", "filesystem"),
        ("filesystem.write", "Write file", "Write a local file and verify it.", "filesystem"),
        ("filesystem.copy", "Copy file", "Copy a file or directory.", "filesystem"),
        ("filesystem.move", "Move file", "Move a file or directory.", "filesystem"),
        ("filesystem.delete", "Delete file", "Delete a file or directory.", "filesystem"),
        ("terminal.execute", "Execute terminal command", "Run a shell-native command in an explicit cwd.", "system"),
        ("screen.capture", "Capture screen", "Capture a fresh desktop frame.", "vision"),
        ("vision.inspect", "Inspect screen", "Inspect a fresh visual frame.", "vision"),
        ("window.focus", "Focus window", "Bring a window to the foreground.", "window"),
        ("window.minimize", "Minimize window", "Minimize a window.", "window"),
        ("window.maximize", "Maximize window", "Maximize a window.", "window"),
        ("process.start", "Start process", "Start a process with structured argv.", "system"),
        ("process.stop", "Stop process", "Stop a process by PID.", "system"),
        ("download.file", "Download file", "Download a file and verify its presence.", "network"),
        ("upload.file", "Upload file", "Upload a file through an available backend.", "network"),
        ("git.clone", "Clone git repository", "Clone a repository into the workspace.", "development"),
        ("git.pull", "Pull git repository", "Pull repository changes.", "development"),
        ("git.push", "Push git changes", "Push committed changes.", "development"),
        ("code.inspect", "Inspect code", "Inspect project code and execution state.", "development"),
        ("code.edit", "Edit code", "Edit project code and preserve workspace state.", "development"),
        ("code.test", "Test code", "Run the relevant test suite and collect evidence.", "development"),
        ("code.build", "Build code", "Build the project and verify the build result.", "development"),
    ]
    for capability_id, name, description, category in specs:
        readiness = {
            "browser.youtube.play": "youtube_player_ready",
            "browser.youtube.pause": "youtube_player_ready",
            "browser.youtube.search": "youtube_search_ready",
            "whatsapp.open": "whatsapp_ready",
            "whatsapp.search_contact": "whatsapp_ready",
            "whatsapp.send_message": "whatsapp_composer_ready",
        }.get(capability_id)
        verifier = {
            "browser.youtube.play": "playback_state",
            "browser.youtube.pause": "playback_state",
            "whatsapp.send_message": "sent_message",
            "filesystem.write": "file_exists_and_hash",
            "terminal.execute": "exit_code_and_output",
            "app.launch": "process_and_foreground_window",
            "browser.navigate": "url_and_dom_readiness",
        }.get(capability_id)
        permission_map = {
            "filesystem": ["read", "write", "execute"],
            "development": ["read", "write", "execute"],
            "network": ["network", "execute"],
            "browser": ["network", "execute"],
        }
        yield CapabilitySpec(
            capability_id=capability_id,
            name=name,
            description=description,
            category=category,
            supported_backends=["native", "uia", "dom", "cdp", "playwright", "vision", "terminal"],
            verifier=verifier,
            readiness_probe=readiness,
            permissions=permission_map.get(category, ["execute"]),
        )


class CapabilityRegistry:
    def __init__(self) -> None:
        self._lock = RLock()
        self._items: dict[str, CapabilitySpec] = {}
        for spec in _builtin_capabilities():
            self.register(spec)

    def register(self, spec: CapabilitySpec) -> None:
        with self._lock:
            self._items[spec.capability_id] = spec

    def get(self, capability_id: str) -> CapabilitySpec | None:
        with self._lock:
            return self._items.get(capability_id)

    def all(self) -> list[CapabilitySpec]:
        with self._lock:
            return list(self._items.values())

    def validate(self, capability_id: str) -> bool:
        return self.get(capability_id) is not None

    def discover(self, query: str, limit: int = 8) -> list[CapabilitySpec]:
        """Discover capabilities using exact token matches, not substring matches.

        Natural-language mission text can contain common words that happen to appear
        inside unrelated capability descriptions. Substring matching can therefore
        route a generic task to the wrong executor (for example, YouTube).
        Tokenize both sides, ignore common stop words, and score exact matches with a
        small bonus for capability-id segments.
        """
        raw_tokens = re.findall(r"[a-z0-9]+", str(query).lower())
        stop_words = {
            "a", "an", "and", "are", "can", "could", "do", "for", "from",
            "how", "i", "in", "is", "it", "me", "my", "of", "on", "or",
            "please", "the", "this", "to", "we", "what", "with", "you",
        }
        tokens = {token for token in raw_tokens if token not in stop_words}
        if not tokens:
            return []

        scored = []
        for spec in self.all():
            capability_id_tokens = set(re.findall(r"[a-z0-9]+", spec.capability_id.lower()))
            text_tokens = set(
                re.findall(r"[a-z0-9]+", f"{spec.name} {spec.description} {spec.category}".lower())
            )
            matched = tokens & (capability_id_tokens | text_tokens)
            if not matched:
                continue

            score = len(matched)
            score += 2 * len(tokens & capability_id_tokens)
            scored.append((score, spec))

        scored.sort(key=lambda item: (-item[0], item[1].capability_id))
        return [spec for _, spec in scored[:limit]]


_global_registry: CapabilityRegistry | None = None


def get_capability_registry() -> CapabilityRegistry:
    global _global_registry
    if _global_registry is None:
        _global_registry = CapabilityRegistry()
    return _global_registry
