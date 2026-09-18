import unittest
from unittest.mock import patch, MagicMock
import requests

from kratos_agent.brain.config import (
    DEFAULT_CHAT_ENDPOINT,
    BrainConnectionError,
    BrainBadRequestError,
)
from kratos_agent.brain.client import BrainClient
from kratos_agent.brain.chat_model import extract_tool_calls_from_text
from kratos_agent.brain.fetch_model import get_model
from kratos_agent.brain.brain import get_agent_response


class BrainTransportTests(unittest.TestCase):
    def setUp(self):
        self.client = BrainClient(endpoint_url=DEFAULT_CHAT_ENDPOINT)

    def test_build_envelope_format(self):
        envelope = self.client.build_envelope(
            "antigravity/gemini-3.7-flash-high",
            [{"role": "user", "content": "hello"}],
            system_instruction="system test",
            stream=True,
        )
        self.assertEqual(envelope["model"], "antigravity/gemini-3.7-flash-high")
        self.assertTrue(envelope["stream"])
        self.assertEqual(envelope["messages"][0]["role"], "system")
        self.assertEqual(envelope["messages"][0]["content"], "system test")
        self.assertEqual(envelope["messages"][1]["role"], "user")
        self.assertEqual(envelope["messages"][1]["content"], "hello")

    def test_session_trust_env_disabled(self):
        session = self.client.session
        self.assertFalse(session.trust_env)

    @patch("requests.Session.post")
    def test_streaming_sse_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_lines.return_value = [
            'data: {"choices": [{"delta": {"content": "Hello "}}]}',
            'data: {"choices": [{"delta": {"content": "Brain!"}}]}',
            'data: [DONE]'
        ]
        mock_post.return_value.__enter__.return_value = mock_resp

        result = self.client.generate("antigravity/gemini-3.7-flash-high", [{"role": "user", "content": "hi"}])
        self.assertEqual(result, "Hello Brain!")

    @patch("requests.Session.post")
    def test_non_streaming_json_fallback(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_lines.return_value = []
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Non-streaming answer"}}]
        }
        mock_post.return_value.__enter__.return_value = mock_resp

        result = self.client.generate("antigravity/gemini-3.7-flash-high", [{"role": "user", "content": "hi"}])
        self.assertEqual(result, "Non-streaming answer")

    @patch("requests.Session.post")
    def test_direct_non_streaming_mode(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Direct response"}}]
        }
        mock_post.return_value = mock_resp

        result = self.client.generate("antigravity/gemini-3.7-flash-high", [{"role": "user", "content": "hi"}], stream=False)
        self.assertEqual(result, "Direct response")

    @patch("requests.Session.post")
    def test_connection_error_raises_friendly_error(self, mock_post):
        mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")

        with self.assertRaises(BrainConnectionError) as ctx:
            self.client.generate("antigravity/gemini-3.7-flash-high", [{"role": "user", "content": "hi"}], max_retries=1)
        self.assertIn("Brain LLM is not running on", str(ctx.exception))
        self.assertIn("connection refused", str(ctx.exception))

    @patch("requests.Session.post")
    def test_bad_request_error_raises_without_retry(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {"error": {"message": "Invalid model parameter"}}
        mock_resp.text = "Invalid model parameter"
        mock_post.return_value.__enter__.return_value = mock_resp

        with self.assertRaises(BrainBadRequestError) as ctx:
            self.client.generate("antigravity/gemini-3.7-flash-high", [{"role": "user", "content": "hi"}], max_retries=2)
        self.assertIn("Invalid model request to Brain", str(ctx.exception))
        self.assertEqual(mock_post.call_count, 1)  # No retry on 400

    def test_tool_calling_extraction_from_coding_output(self):
        raw_text = 'call:write_file{file_path: "index.html", content: "<h1>Ben 10 WebApp</h1>"}'
        text, tool_calls = extract_tool_calls_from_text(raw_text)
        self.assertEqual(len(tool_calls), 1)
        self.assertEqual(tool_calls[0]["name"], "write_file")
        self.assertEqual(tool_calls[0]["args"]["file_path"], "index.html")
        self.assertIn("Ben 10", tool_calls[0]["args"]["content"])

    def test_tool_calling_extraction_with_nested_css_and_js(self):
        raw_text = 'I will create the HTML file.\ncall:write_file{"file_path": "ben10.html", "content": "<style>body { background: #000; } .card { border: 1px solid red; }</style><script>function test() { return { ok: true }; }</script>"}\nDone!'
        text, tool_calls = extract_tool_calls_from_text(raw_text)
        self.assertEqual(len(tool_calls), 1)
        self.assertEqual(tool_calls[0]["name"], "write_file")
        self.assertEqual(tool_calls[0]["args"]["file_path"], "ben10.html")
        self.assertIn("function test() { return { ok: true }; }", tool_calls[0]["args"]["content"])
        self.assertIn("I will create the HTML file.", text)
        self.assertIn("Done!", text)
        self.assertNotIn("call:write_file", text)

    @patch("requests.Session.get")
    def test_fetch_model_endpoint(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {"id": "custom-brain-model-1"},
                {"id": "custom-brain-model-2"}
            ]
        }
        mock_get.return_value = mock_resp

        models = get_model(endpoint="http://127.0.0.1:20128/v1/models")
        self.assertEqual(models, ["custom-brain-model-1", "custom-brain-model-2"])

    @patch.object(BrainClient, "generate")
    def test_get_agent_response_function(self, mock_generate):
        mock_generate.return_value = "Hello from Brain Agent!"
        resp = get_agent_response("Hi there")
        self.assertEqual(resp, "Hello from Brain Agent!")


if __name__ == "__main__":
    unittest.main()
