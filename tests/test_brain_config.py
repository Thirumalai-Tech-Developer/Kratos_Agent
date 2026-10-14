import os
import unittest
import tempfile
from pathlib import Path
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
            "KRATOS_BASE_URL", "KRATOS_CHAT_ENDPOINT", "KRATOS_MODEL_ENDPOINT",
            "KRATOS_MODEL", "KRATOS_TIMEOUT", "KRATOS_MAX_RETRIES",
            "KRATOS_MODEL_PROVIDER", "KRATOS_RUNTIME_MODEL", "KRATOS_RUNTIME_ACCOUNT_ID",
            "KRATOS_CATALOG_CACHE_PATH",
            "KRATOS_API_KEY", "BRAIN_BASE_URL", "CHAT_BASE_URL", "OMNIROUTE_BASE_URL",
            "CHAT_ENDPOINT", "BRAIN_CHAT_URL", "KRATOS_API_URL", "OMNIROUTE_CHAT_URL",
            "MODEL_ENDPOINT", "BRAIN_MODEL_URL", "BRAIN_MODEL", "OMNIROUTE_MODEL",
            "NORMAL_MODE_MODEL", "BRAIN_TIMEOUT", "OMNIROUTE_TIMEOUT",
            "BRAIN_MAX_RETRIES", "OMNIROUTE_MAX_RETRIES", "OMNI_KEY", "BRAIN_KEY",
            "OPENAI_API_KEY", "API_KEY",
        )
        for k in keys:
            self.orig_env[k] = os.environ.get(k)
            os.environ.pop(k, None)
        os.environ["KRATOS_MODEL_PROVIDER"] = "gateway"
        self.catalog_directory = tempfile.TemporaryDirectory(prefix="kratos-catalog-test-")
        os.environ["KRATOS_CATALOG_CACHE_PATH"] = str(Path(self.catalog_directory.name) / "catalog.json")

    def tearDown(self):
        self.catalog_directory.cleanup()
        for k, v in self.orig_env.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    def test_default_config_values(self):
        self.assertEqual(DEFAULT_BASE_URL, "http://127.0.0.1:20128/v1")
        self.assertEqual(DEFAULT_CHAT_ENDPOINT, "http://127.0.0.1:20128/v1/chat/completions")
        self.assertEqual(DEFAULT_MODEL_ENDPOINT, "http://127.0.0.1:20128/v1/models")
        self.assertEqual(DEFAULT_MODEL, "")
        self.assertEqual(get_base_url(), "http://127.0.0.1:20128/v1")
        self.assertEqual(get_endpoint_url(), "http://127.0.0.1:20128/v1/chat/completions")
        self.assertEqual(get_model_endpoint_url(), "http://127.0.0.1:20128/v1/models")
        self.assertEqual(get_default_model(), "")
        self.assertEqual(get_request_timeout(), 60.0)
        self.assertEqual(get_max_retries(), 2)
        self.assertEqual(PUBLIC_MODELS, [])

    def test_client_initialization_with_env_override(self):
        os.environ["KRATOS_BASE_URL"] = "http://127.0.0.1:9999/v1"
        client = BrainClient()
        self.assertEqual(client.endpoint_url, "http://127.0.0.1:9999/v1/chat/completions")

    def test_client_trust_env_disabled(self):
        client = BrainClient()
        self.assertFalse(client.session.trust_env)

    def test_timeout_and_retries_override(self):
        os.environ["KRATOS_TIMEOUT"] = "120"
        os.environ["KRATOS_MAX_RETRIES"] = "3"
        self.assertEqual(get_request_timeout(), 120.0)
        self.assertEqual(get_max_retries(), 3)

    def test_kratos_env_keys(self):
        os.environ["KRATOS_CHAT_ENDPOINT"] = "http://kratos.local/v1/chat/completions"
        os.environ["KRATOS_MODEL_ENDPOINT"] = "http://kratos.local/v1/models"
        os.environ["KRATOS_API_KEY"] = "secret-kratos-key"

        self.assertEqual(get_endpoint_url(), "http://kratos.local/v1/chat/completions")
        self.assertEqual(get_model_endpoint_url(), "http://kratos.local/v1/models")
        self.assertEqual(get_api_key(), "secret-kratos-key")
        headers = authenticate()
        self.assertEqual(headers.get("Authorization"), "Bearer secret-kratos-key")

    def test_gateway_model_catalog_exposes_only_configured_kratos_id(self):
        from unittest.mock import patch, MagicMock
        from kratos_agent.brain import config
        os.environ["KRATOS_MODEL"] = "kratos-reasoning-v1"
        config._cached_models = []
        config._cached_model_details = {}

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {"id": "kratos-reasoning-v1"},
                {"id": "unconfigured-model-a"},
                {"id": "unconfigured-model-b"}
            ]
        }
        with patch("requests.Session.get", return_value=mock_resp):
            models = config.get_model(endpoint="http://127.0.0.1:20128/v1/models", refresh=True)
            self.assertEqual(models, ["kratos-reasoning-v1"])

    def test_model_catalog_id_schemas(self):
        from kratos_agent.brain.config import _extract_model_ids

        # A gateway may expose a model list using either the models or data key.
        gateway_payload = {"models": [{"name": "kratos-local-coder"}, {"model": "kratos-local-reasoner"}]}
        self.assertEqual(_extract_model_ids(gateway_payload), ["kratos-local-coder", "kratos-local-reasoner"])

        # Flat list style
        list_payload = ["custom-model-1", "custom-model-2"]
        self.assertEqual(_extract_model_ids(list_payload), ["custom-model-1", "custom-model-2"])

        # Dict with id style
        dict_payload = {"data": ["model-alpha", "model-beta"]}
        self.assertEqual(_extract_model_ids(dict_payload), ["model-alpha", "model-beta"])

    def test_dynamic_model_fetch_fallback_on_error(self):
        from unittest.mock import patch
        from kratos_agent.brain.config import get_model
        os.environ["KRATOS_MODEL"] = "kratos-reasoning-v1"

        with patch("requests.Session.get", side_effect=Exception("Connection refused")):
            models = get_model(endpoint="http://invalid.local/models", refresh=True)
            self.assertEqual(models, ["kratos-reasoning-v1"])

    def test_only_kratos_model_is_used(self):
        os.environ["BRAIN_MODEL"] = "legacy-model"
        self.assertEqual(get_default_model(), "")

        os.environ["KRATOS_MODEL"] = "kratos-reasoning-v1"
        self.assertEqual(get_default_model(), "kratos-reasoning-v1")

    def test_openai_key_is_not_used_as_a_model_or_gateway_key_fallback(self):
        os.environ["BRAIN_MODEL"] = "legacy-model"
        os.environ["OPENAI_API_KEY"] = "should-not-be-used"
        self.assertEqual(get_default_model(), "")
        self.assertEqual(get_api_key(), "")


if __name__ == "__main__":
    unittest.main()
