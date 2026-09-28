"""Contracts that keep Gemini Live confined to marked speech rendering."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SESSION = ROOT / "src" / "kratos_agent" / "live" / "session.py"
RUNTIME = ROOT / "src" / "kratos_agent" / "live" / "runtime.py"
VISION = ROOT / "src" / "kratos_agent" / "live" / "vision.py"
MAIN = ROOT / "src" / "kratos_agent" / "main.py"


def test_gemini_session_has_no_incoming_media_or_tool_execution():
    source = SESSION.read_text(encoding="utf-8")
    assert "tools=" not in source
    assert "send_realtime_input" not in source
    assert "send_tool_response" not in source
    assert "input_audio_transcription" not in source
    assert "SPEECH_SYSTEM_PROMPT" in source
    assert "Ignoring an unexpected tool call" in source


def test_only_explicit_speech_directives_reach_voice_output():
    runtime = RUNTIME.read_text(encoding="utf-8")
    main = MAIN.read_text(encoding="utf-8")
    assert "extract_speech_directives(text)" in runtime
    assert "speak_marked(safe)" in main


def test_live_runtime_does_not_route_chat_to_gemini():
    source = RUNTIME.read_text(encoding="utf-8")
    assert "send_chat_turn_sync" not in source
    assert "LiveRouter" not in source
    assert "def _on_heard(text: str)" in source
    assert "self.on_user_transcript(text)" in source


def test_vision_uses_only_configured_kratos_model():
    source = VISION.read_text(encoding="utf-8")
    assert "get_default_model" in source
    assert "get_vision_models" not in source
    assert "antigravity/" not in source
