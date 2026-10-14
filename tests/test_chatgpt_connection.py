import base64
import hashlib
import json
import os
import time
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from kratos_agent.brain.account_store import AccountStore
from kratos_agent.brain.chatgpt_auth import (
    ISSUER,
    PLAN_SCOPE,
    RESOURCE,
    TOKEN,
    ChatGPTAccounts,
    ChatGPTConnectionError,
    validate_identity,
)
from kratos_agent.brain.chatgpt_transport import responses_request
from kratos_agent.brain.config import BrainError, BrainRateLimitError
from kratos_agent.core.archive import ExecutionArchive, redact
from kratos_agent.sdk.client import KratosClient


def response(body, status=200):
    result = Mock(status_code=status)
    result.json.return_value = body
    return result


def tokens(**overrides):
    return {
        "access_token": "test-private-access-credential",
        "refresh_token": "test-private-renewal-credential",
        "id_token": "test-private-identity-credential",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": PLAN_SCOPE + " offline_access openid",
        **overrides,
    }


def connected_store(tmp_path):
    store = AccountStore(tmp_path / "user-storage")
    state = store.read()
    state.update({"active_account": "registration", "provider": "chatgpt"})
    state["accounts"]["registration"] = {
        **tokens(),
        "client_id": "oaiapp_kratos",
        "subject": "identity-1",
        "model": "account-model",
        "expires_at": time.time() + 3600,
        "scopes": [PLAN_SCOPE],
        "email": "owner@example.com",
    }
    with store.locked():
        store.write(state)
    return store


@pytest.fixture
def connection(tmp_path, monkeypatch):
    store = connected_store(tmp_path)
    manager = ChatGPTAccounts(store, Mock())
    monkeypatch.setattr("kratos_agent.brain.account_store.account_store", store)
    monkeypatch.setattr("kratos_agent.brain.chatgpt_auth.chatgpt_accounts", manager)
    monkeypatch.setattr(
        "kratos_agent.brain.chatgpt_transport.chatgpt_accounts", manager
    )
    monkeypatch.delenv("KRATOS_MODEL_PROVIDER", raising=False)
    return manager


def test_credentials_are_protected_and_redacted(tmp_path):
    store = connected_store(tmp_path)
    assert (
        store.read()["accounts"]["registration"]["access_token"]
        == tokens()["access_token"]
    )
    if os.name == "nt":
        assert tokens()["access_token"].encode() not in store.path.read_bytes()
    else:
        assert store.path.stat().st_mode & 0o777 == 0o600
    archive = ExecutionArchive(tmp_path / "workspace" / "archive")
    archive.record(
        "tool.result",
        {
            "text": tokens()["access_token"],
            "id_token": "never retained",
            "cookie": "private",
        },
    )
    item = archive.records()[0]["payload"]
    assert set(item.values()) == {"[REDACTED]"}
    assert archive.capture_file(store.path)["excluded"] == "credential_file"


def test_oauth_uses_pkce_loopback_and_rejects_mismatched_or_replayed_state(
    tmp_path, monkeypatch
):
    manager = ChatGPTAccounts(AccountStore(tmp_path / "profile"), Mock())
    monkeypatch.setattr(
        "kratos_agent.brain.chatgpt_auth.validate_identity",
        lambda *_: {"sub": "identity-1", "email": "owner@example.com"},
    )
    manager.session.request.return_value = response(tokens())
    login = manager.start_login()
    query = parse_qs(urlparse(login["authorization_url"]).query)
    attempt = manager.attempts[login["attempt_id"]]
    assert query["client_id"] == ["dynamic_agent_client"]
    assert urlparse(query["redirect_uri"][0]).hostname == "127.0.0.1"
    assert urlparse(query["redirect_uri"][0]).path == "/auth/callback"
    assert (
        query["code_challenge"][0]
        == base64.urlsafe_b64encode(
            hashlib.sha256(attempt["verifier"].encode()).digest()
        )
        .rstrip(b"=")
        .decode()
    )
    with pytest.raises(ChatGPTConnectionError, match="state"):
        manager.finish_login(
            login["attempt_id"], {"state": ["wrong"], "code": ["code"]}
        )
    assert not manager.session.request.called
    manager.finish_login(
        login["attempt_id"],
        {"state": query["state"], "code": ["code"], "client_id": ["oaiapp_issued"]},
    )
    assert manager.login_status(login["attempt_id"])["status"] == "completed"
    post = manager.session.request.call_args
    assert post.args == ("POST", TOKEN)
    assert post.kwargs["data"]["client_id"] == "oaiapp_issued"
    assert post.kwargs["data"]["redirect_uri"] == query["redirect_uri"][0]
    assert manager.store.read()["provider"] == "gateway"  # selection is explicit
    with pytest.raises(ChatGPTConnectionError, match="already used"):
        manager.finish_login(
            login["attempt_id"], {"state": query["state"], "code": ["code"]}
        )
    assert manager.session.request.call_count == 1


@pytest.mark.parametrize(
    "callback",
    [
        {"error": ["access_denied"]},
        {"code": ["c"]},
        {"code": ["c"], "client_id": ["dynamic_agent_client"]},
    ],
)
def test_declined_or_incomplete_registration_never_overwrites_account(
    tmp_path, callback
):
    manager = ChatGPTAccounts(AccountStore(tmp_path / "user"), Mock())
    attempt = manager.start_login()
    callback = {**callback, "state": [manager.attempts[attempt["attempt_id"]]["state"]]}
    with pytest.raises(ChatGPTConnectionError):
        manager.finish_login(attempt["attempt_id"], callback)
    assert not manager.session.request.called
    assert manager.store.read()["accounts"] == {}


def test_identity_validation_checks_signature_issuer_audience_nonce_and_expiry():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk["kid"] = "test-key"
    session = Mock()
    session.request.side_effect = lambda method, url, **_: response(
        {
            "issuer": ISSUER,
            "jwks_uri": ISSUER + "/.well-known/jwks.json",
            "revocation_endpoint": ISSUER + "/api/accounts/oauth/revoke",
        }
        if "openid-configuration" in url
        else {"keys": [jwk]}
    )
    base = {
        "sub": "identity",
        "iss": ISSUER,
        "aud": "issued-client",
        "nonce": "original-nonce",
        "iat": time.time(),
        "exp": time.time() + 120,
    }

    def signed(claims, signing_key=key):
        return jwt.encode(
            claims, signing_key, algorithm="RS256", headers={"kid": "test-key"}
        )

    assert (
        validate_identity(
            {"id_token": signed(base)}, "issued-client", "original-nonce", session
        )["sub"]
        == "identity"
    )
    for changes in (
        {"iss": "https://wrong.example"},
        {"aud": "wrong-client"},
        {"nonce": "wrong"},
        {"exp": time.time() - 30},
    ):
        with pytest.raises(ChatGPTConnectionError, match="verification"):
            validate_identity(
                {"id_token": signed({**base, **changes})},
                "issued-client",
                "original-nonce",
                session,
            )
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(ChatGPTConnectionError, match="verification"):
        validate_identity(
            {"id_token": signed(base, wrong_key)},
            "issued-client",
            "original-nonce",
            session,
        )


def test_models_and_generation_use_same_account_and_ignore_workspace_gateway(
    connection, monkeypatch
):
    from kratos_agent.brain.config import (
        get_default_model,
        get_endpoint_url,
        get_model_catalog,
    )

    monkeypatch.setenv("KRATOS_MODEL", "unrelated-workspace-model")
    monkeypatch.setenv("KRATOS_CHAT_ENDPOINT", "http://workspace.invalid/chat")
    connection.session.request.return_value = response(
        {
            "models": [
                {
                    "slug": "account-model",
                    "display_name": "Account model",
                    "visibility": "list",
                },
                {"slug": "hidden-model", "visibility": "hidden"},
            ]
        }
    )
    assert get_default_model() == "account-model"
    assert get_endpoint_url() == RESOURCE + "/responses"
    assert [m["id"] for m in get_model_catalog()] == ["account-model"]
    assert (
        connection.session.request.call_args.kwargs["headers"]["Authorization"]
        == "Bearer " + tokens()["access_token"]
    )
    assert "access_token" not in json.dumps(connection.status())
    with pytest.raises(ChatGPTConnectionError, match="advertised"):
        connection.select("registration", "hidden-model")


def test_token_rotation_is_atomic_and_grant_required(connection):
    state = connection.store.read()
    state["accounts"]["registration"]["expires_at"] = 0
    with connection.store.locked():
        connection.store.write(state)
    connection.session.request.return_value = response(
        tokens(
            access_token="rotated-access-token", refresh_token="rotated-renewal-token"
        )
    )
    assert connection.access_token() == "rotated-access-token"
    assert connection.access_token() == "rotated-access-token"
    assert connection.session.request.call_count == 1
    stored = connection.store.read()["accounts"]["registration"]
    assert stored["refresh_token"] == "rotated-renewal-token"
    state["accounts"]["registration"]["expires_at"] = 0
    with connection.store.locked():
        connection.store.write(state)
    connection.session.request.return_value = response(tokens(scope="openid email"))
    with pytest.raises(ChatGPTConnectionError, match="not authorized"):
        connection.access_token()


def test_responses_payload_maps_history_tools_and_omits_rejected_fields():
    payload = {
        "model": "account-model",
        "max_tokens": 16384,
        "temperature": 1,
        "messages": [
            {"role": "system", "content": "instructions"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "inspect"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "https://example.com/image.png"},
                    },
                ],
            },
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-1",
                        "function": {"name": "read_file", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "file contents"},
        ],
        "tools": [
            {"function": {"name": "read_file", "parameters": {"type": "object"}}}
        ],
    }
    converted = responses_request(payload)
    assert converted["store"] is False and converted["stream"] is True
    assert (
        "max_output_tokens" not in converted
        and "max_tokens" not in converted
        and "temperature" not in converted
    )
    assert converted["instructions"] == "instructions"
    assert converted["input"][0]["content"][1]["type"] == "input_image"
    assert converted["input"][1]["namespace"] == "kratos"
    assert converted["input"][2] == {
        "type": "function_call_output",
        "call_id": "call-1",
        "output": "file contents",
    }
    assert converted["tools"][0]["type"] == "namespace"


class Stream:
    status_code = 200

    def __init__(self, events):
        self.events = events

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def iter_lines(self, **_):
        for event in self.events:
            yield ("data: " + json.dumps(event)).encode()
            yield b""


def test_stream_requires_completion_and_preserves_native_tool_continuation(connection):
    client = KratosClient()
    opaque = {
        "type": "reasoning",
        "id": "reason-1",
        "summary": [],
        "encrypted_content": "opaque-context",
    }
    client.session.post = Mock(
        return_value=Stream(
            [
                {"type": "response.output_text.delta", "delta": "Checking"},
                {
                    "type": "response.completed",
                    "response": {
                        "status": "completed",
                        "output": [
                            opaque,
                            {
                                "type": "function_call",
                                "call_id": "call-1",
                                "name": "read_file",
                                "namespace": "kratos",
                                "arguments": '{"path":"README.md"}',
                            },
                        ],
                        "usage": {
                            "input_tokens": 5,
                            "output_tokens": 3,
                            "total_tokens": 8,
                        },
                    },
                },
            ]
        )
    )
    chunks = []
    result = client.complete(
        client.build_request("account-model", [{"role": "user", "content": "inspect"}]),
        on_chunk=chunks.append,
    )
    assert chunks == ["Checking"]
    assert result.tool_calls[0].arguments == {"path": "README.md"}
    assert result.usage["total_tokens"] == 8
    call = result.tool_calls[0]
    next_request = client.build_request(
        "account-model",
        [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": call.id,
                        "name": call.name,
                        "args": call.arguments,
                        "provider_items": call.provider_items,
                    }
                ],
            }
        ],
    )
    assert responses_request(next_request)["input"][0] == opaque
    assert client.session.post.call_args.args[0] == RESOURCE + "/responses"
    assert (
        client.session.post.call_args.kwargs["headers"]["Authorization"]
        == "Bearer " + tokens()["access_token"]
    )


@pytest.mark.parametrize(
    "ending", [None, "response.failed", "response.incomplete", "error"]
)
def test_partial_text_is_never_false_success(connection, ending):
    client = KratosClient()
    events = [{"type": "response.output_text.delta", "delta": "partial"}]
    if ending:
        events.append({"type": ending})
    client.session.post = Mock(return_value=Stream(events))
    with pytest.raises(BrainError):
        client.complete({"model": "account-model", "messages": []})
    assert client.session.post.call_count == 1  # No gateway fallback or replay.


def test_usage_limit_after_stream_started_is_visible(connection):
    client = KratosClient()
    client.session.post = Mock(
        return_value=Stream(
            [
                {"type": "response.output_text.delta", "delta": "partial"},
                {
                    "type": "response.failed",
                    "response": {
                        "error": {"code": "subscription_sharing_usage_limit_exceeded"}
                    },
                },
            ]
        )
    )
    with pytest.raises(BrainRateLimitError, match="usage"):
        client.complete({"model": "account-model", "messages": []})


def test_public_text_stream_emits_deltas_before_terminal_event(connection):
    client = KratosClient()
    client.session.post = Mock(
        return_value=Stream(
            [
                {"type": "response.output_text.delta", "delta": "Hello"},
                {"type": "response.output_text.delta", "delta": " there"},
                {
                    "type": "response.completed",
                    "response": {
                        "status": "completed",
                        "output": [
                            {
                                "type": "message",
                                "content": [
                                    {"type": "output_text", "text": "Hello there"}
                                ],
                            }
                        ],
                    },
                },
            ]
        )
    )
    iterator = client.stream_text({"model": "account-model", "messages": []})
    assert next(iterator) == "Hello"
    assert next(iterator) == " there"
    assert list(iterator) == []


def test_signout_clears_local_tokens_when_revocation_unconfirmed(connection):
    connection.session.request.return_value = response(
        {
            "issuer": ISSUER,
            "jwks_uri": ISSUER + "/jwks",
            "revocation_endpoint": ISSUER + "/revoke",
        }
    )
    connection.session.post.return_value = response({}, status=503)
    result = connection.sign_out("registration")
    assert result["signed_out"] and not result["revocation_confirmed"]
    assert "access_token" not in connection.store.read()["accounts"]["registration"]
    with pytest.raises(ChatGPTConnectionError, match="Connect"):
        connection.access_token()
    assert redact({"cookie": "private"})["cookie"] == "[REDACTED]"


def test_parallel_workers_refresh_one_rotating_grant(connection):
    from concurrent.futures import ThreadPoolExecutor

    state = connection.store.read()
    state["accounts"]["registration"]["expires_at"] = 0
    with connection.store.locked():
        connection.store.write(state)

    def token_request(*_, **kwargs):
        time.sleep(0.04)
        return response(
            tokens(
                access_token="shared-rotated-access",
                refresh_token="shared-rotated-refresh",
            )
        )

    connection.session.request.side_effect = token_request

    def request_token(_):
        return ChatGPTAccounts(
            AccountStore(connection.store.root), connection.session
        ).access_token()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(request_token, range(4)))
    assert results == ["shared-rotated-access"] * 4
    assert connection.session.request.call_count == 1
