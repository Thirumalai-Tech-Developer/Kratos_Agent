from kratos_agent.input.router import get_input_router


def build_web_input(text: str, *, session_id: str | None = None, **context):
    return get_input_router().build(text, source="web", session_id=session_id, **context)
