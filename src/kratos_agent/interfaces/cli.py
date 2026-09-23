from kratos_agent.input.router import get_input_router


def build_cli_input(text: str, session_id: str | None = None):
    return get_input_router().build(text, source="cli", session_id=session_id)
