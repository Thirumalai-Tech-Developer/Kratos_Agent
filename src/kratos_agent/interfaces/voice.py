from kratos_agent.input.router import get_input_router


def build_voice_input(text: str = "", *, audio_metadata=None, session_id: str | None = None):
    return get_input_router().build(text, source="voice", session_id=session_id, audio_metadata=audio_metadata or {})
