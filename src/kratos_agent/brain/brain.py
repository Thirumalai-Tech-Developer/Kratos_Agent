from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
import httpx

from langchain_openai import ChatOpenAI
from kratos_agent.brain.config import (
    authenticate,
    get_api_key,
    get_base_url,
    get_endpoint_url,
    get_default_model,
)
from kratos_agent.brain.client import BrainClient

def get_http_client() -> httpx.Client:
    """Returns an httpx.Client with trust_env=False to bypass system proxies."""
    return httpx.Client(trust_env=False)


def create_brain_llm(
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> ChatOpenAI:
    """Creates a LangChain ChatOpenAI instance configured for the Brain gateway."""
    target_model = model or get_default_model()
    target_base_url = (base_url or get_base_url()).rstrip("/")
    target_api_key = api_key or get_api_key() or "kratos-brain-key"
    client = get_http_client()

    return ChatOpenAI(
        model=target_model,
        base_url=target_base_url,
        api_key=target_api_key,
        http_client=client,
    )


def get_agent_response(
    query: str,
    model: Optional[str] = None,
    endpoint_url: Optional[str] = None,
) -> str:
    """Sends a query to the LLM Brain and returns the response content."""
    target_model = model or get_default_model()
    client = BrainClient(endpoint_url=endpoint_url or get_endpoint_url())

    response = client.generate(
        model=target_model,
        messages=[{"role": "user", "content": query}],
        stream=False,
    )
    return response
