import os
import unittest
from kratos_agent.brain.config import (
    DEFAULT_BASE_URL,
    DEFAULT_CHAT_ENDPOINT,
    DEFAULT_MODEL_ENDPOINT,
    DEFAULT_MODEL,
    PUBLIC_MODELS,
    get_base_url,
    get_endpoint_url,
    get_model_endpoint_url,
    get_default_model,
    get_request_timeout,
    get_max_retries,
    get_api_key,
    authenticate,
)
from kratos_agent.brain.client import BrainClient


class BrainConfigTests(unittest.TestCase):
    def setUp(self):
        self.orig_env = {}
        keys = (
            "BRAIN_BASE_URL", "CHAT_BASE_URL", "OMNIROUTE_BASE_URL",
            "CHAT_ENDPOINT", "BRAIN_CHAT_URL", "KRATOS_API_URL", "OMNIROUTE_CHAT_URL",
            "MODEL_ENDPOINT", "BRAIN_MODEL_URL",
            "BRAIN_MODEL", "OMNIROUTE_MODEL", "KRATOS_MODEL",
            "BRAIN_TIMEOUT", "OMNIROUTE_TIMEOUT", "KRATOS_TIMEOUT",
            "BRAIN_MAX_RETRIES", "OMNIROUTE_MAX_RETRIES", "KRATOS_MAX_RETRIES",
            "OMNI_KEY", "BRAIN_KEY", "KRATOS_API_KEY", "OPENAI_API_KEY",
        )
        for k in keys:
            self.orig_env[k] = os.environ.get(k)
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self.orig_env.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    def test_default_config_values(self):
        self.assertEqual(DEFAULT_BASE_URL, "http://127.0.0.1:20128/v1")
        self.assertEqual(DEFAULT_CHAT_ENDPOINT, "http://127.0.0.1:20128/v1/chat/completions")
        self.assertEqual(DEFAULT_MODEL_ENDPOINT, "http://127.0.0.1:20128/v1/models")
        self.assertEqual(DEFAULT_MODEL, "antigravity/gemini-3.7-flash-high")
        self.assertEqual(get_base_url(), "http://127.0.0.1:20128/v1")
        self.assertEqual(get_endpoint_url(), "http://127.0.0.1:20128/v1/chat/completions")
        self.assertEqual(get_model_endpoint_url(), "http://127.0.0.1:20128/v1/models")
        self.assertEqual(get_default_model(), "antigravity/gemini-3.7-flash-high")
        self.assertEqual(get_request_timeout(), 60.0)
        self.assertEqual(get_max_retries(), 2)
        self.assertTrue(len(PUBLIC_MODELS) > 0)

    def test_client_initialization_with_env_override(self):
        os.environ["BRAIN_BASE_URL"] = "http://127.0.0.1:9999/v1"
        client = BrainClient()
        self.assertEqual(client.endpoint_url, "http://127.0.0.1:9999/v1/chat/completions")

    def test_client_trust_env_disabled(self):
        client = BrainClient()
        self.assertFalse(client.session.trust_env)

    def test_timeout_and_retries_override(self):
        os.environ["BRAIN_TIMEOUT"] = "120"
        os.environ["BRAIN_MAX_RETRIES"] = "3"
        self.assertEqual(get_request_timeout(), 120.0)
        self.assertEqual(get_max_retries(), 3)

    def test_zfusion_env_keys(self):
        os.environ["CHAT_ENDPOINT"] = "http://api.brain.local/v1/chat/completions"
        os.environ["MODEL_ENDPOINT"] = "http://api.brain.local/v1/models"
        os.environ["OMNI_KEY"] = "secret-omni-key"

        self.assertEqual(get_endpoint_url(), "http://api.brain.local/v1/chat/completions")
        self.assertEqual(get_model_endpoint_url(), "http://api.brain.local/v1/models")
        self.assertEqual(get_api_key(), "secret-omni-key")
        headers = authenticate()
        self.assertEqual(headers.get("Authorization"), "Bearer secret-omni-key")

    def test_dynamic_model_fetch_openai_schema(self):
        from unittest.mock import patch, MagicMock
        from kratos_agent.brain.config import get_model

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {"id": "ds-web/deepseek-v4-pro-think"},
                {"id": "claude-3-7-sonnet"}
            ]
        }
        with patch("requests.Session.get", return_value=mock_resp):
            models = get_model(endpoint="http://127.0.0.1:20128/v1/models", refresh=True)
            self.assertEqual(models, ["ds-web/deepseek-v4-pro-think", "claude-3-7-sonnet"])

    def test_dynamic_model_fetch_ollama_and_list_schemas(self):
        from unittest.mock import patch, MagicMock
        from kratos_agent.brain.config import get_model, _extract_model_ids

        # Ollama style
        ollama_payload = {"models": [{"name": "qwen2.5-coder:32b"}, {"model": "deepseek-coder:6.7b"}]}
        self.assertEqual(_extract_model_ids(ollama_payload), ["qwen2.5-coder:32b", "deepseek-coder:6.7b"])

        # Flat list style
        list_payload = ["custom-model-1", "custom-model-2"]
        self.assertEqual(_extract_model_ids(list_payload), ["custom-model-1", "custom-model-2"])

        # Dict with id style
        dict_payload = {"data": ["model-alpha", "model-beta"]}
        self.assertEqual(_extract_model_ids(dict_payload), ["model-alpha", "model-beta"])

    def test_dynamic_model_fetch_fallback_on_error(self):
        from unittest.mock import patch
        from kratos_agent.brain.config import get_model

        with patch("requests.Session.get", side_effect=Exception("Connection refused")):
            models = get_model(endpoint="http://invalid.local/models", refresh=True)
            self.assertTrue(len(models) > 0)


if __name__ == "__main__":
    unittest.main()
