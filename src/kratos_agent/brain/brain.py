"""Small compatibility helpers backed exclusively by the Kratos gateway."""
from __future__ import annotations

from kratos_agent.brain.client import BrainClient
from kratos_agent.brain.config import get_default_model, get_endpoint_url


def get_agent_response(
    query: str,
    model: str | None = None,
    endpoint_url: str | None = None,
) -> str:
    """Send one user message to Kratos and return its text response."""
    client = BrainClient(endpoint_url=endpoint_url or get_endpoint_url())
    return client.generate(
        model=model or get_default_model(),
        messages=[{"role": "user", "content": query}],
        stream=False,
    )
