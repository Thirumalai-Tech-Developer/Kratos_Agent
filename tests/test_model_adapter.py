import unittest

from kratos_agent.core.model_adapter import KratosModelAdapter


class _FakeClient:
    def __init__(self):
        self.kwargs = None

    def complete(self, **kwargs):
        self.kwargs = kwargs
        return "call:read_file{\"file_path\":\"README.md\"}", []


class _GenerateOnlyClient:
    def __init__(self):
        self.kwargs = None

    def generate(self, **kwargs):
        self.kwargs = kwargs
        return "call:read_file{\"file_path\":\"README.md\"}"


class _FailingClient:
    def complete(self, **kwargs):
        raise RuntimeError("401 Invalid API key")


class ProviderRuntimeTests(unittest.TestCase):
    def _request(self):
        return {
            "system": "system",
            "messages": [{"role": "user", "content": "inspect the project"}],
            "tools": [{"type": "function", "function": {"name": "read_file", "parameters": {}}}],
        }

    def test_native_complete_preserves_tools_and_does_not_duplicate_schema(self):
        client = _FakeClient()
        response = KratosModelAdapter("test-model", client).complete(self._request())
        self.assertEqual(response.tool_calls[0].name, "read_file")
        self.assertIn("TOOL EXECUTION RULES", client.kwargs["system_instruction"])
        self.assertNotIn('"name": "read_file"', client.kwargs["system_instruction"])
        self.assertEqual(client.kwargs["tools"], self._request()["tools"])

    def test_generate_fallback_keeps_tools(self):
        client = _GenerateOnlyClient()
        response = KratosModelAdapter("test-model", client).complete(self._request())
        self.assertEqual(response.tool_calls[0].name, "read_file")
        self.assertEqual(client.kwargs["tools"], self._request()["tools"])

    def test_provider_errors_are_not_hidden(self):
        with self.assertRaisesRegex(RuntimeError, "401 Invalid API key"):
            KratosModelAdapter("test-model", _FailingClient()).complete(self._request())


if __name__ == "__main__":
    unittest.main()
