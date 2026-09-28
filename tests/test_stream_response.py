import json
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import tempfile

from kratos_agent.brain.client import BrainClient
from kratos_agent.core.model_adapter import KratosModelAdapter
from kratos_agent.core.runtime_contracts import EventKind, ModelResponse, RuntimeEvent
from kratos_agent.core.agent_loop import AgentLoop
from kratos_agent.core.context_pipeline import ContextBuilder, ContextBudget
from kratos_agent.core.instruction_engine import InstructionEngine
from kratos_agent.core.tool_runtime import ToolRegistry
from kratos_agent.tui.events import EventRenderer
from kratos_agent.tui.live_renderer import KratosLiveRenderer


class StreamResponseTests(unittest.TestCase):
    def setUp(self):
        self.model_env = patch.dict("os.environ", {"KRATOS_MODEL": "test-model"})
        self.model_env.start()

    def tearDown(self):
        self.model_env.stop()

    def test_brain_client_on_chunk_invoked(self):
        client = BrainClient(endpoint_url="http://mock-brain/v1/chat/completions")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.__enter__.return_value = mock_response
        mock_response.iter_lines.return_value = [
            'data: {"choices": [{"delta": {"content": "Hello "}}]}',
            'data: {"choices": [{"delta": {"content": "World!"}}]}',
            'data: [DONE]',
        ]

        received_chunks = []
        with patch.object(client.session, "post", return_value=mock_response):
            result = client.generate(
                model="test-model",
                messages=[{"role": "user", "content": "hi"}],
                stream=True,
                on_chunk=received_chunks.append,
            )

        self.assertEqual(result, "Hello World!")
        self.assertEqual(received_chunks, ["Hello ", "World!"])

    def test_brain_adapter_filters_tool_call_stream(self):
        mock_client = MagicMock()
        # Simulate chunks that form a tool call
        chunks = ["call:write_file", '{"file_path": ', '"app.py", "content": "hi"}']
        
        def fake_generate(model, messages, system_instruction, tools=None, on_chunk=None):
            if on_chunk:
                for c in chunks:
                    on_chunk(c)
            return "".join(chunks)

        mock_client.generate.side_effect = fake_generate
        adapter = KratosModelAdapter("test-model", mock_client)

        streamed = []
        resp = adapter.complete(
            {"messages": [{"role": "user", "content": "write app.py"}]},
            on_chunk=streamed.append,
        )

        # Tool call should NOT be streamed to on_chunk
        self.assertEqual(streamed, [])
        self.assertEqual(len(resp.tool_calls), 1)
        self.assertEqual(resp.tool_calls[0].name, "write_file")

    def test_brain_adapter_streams_natural_language(self):
        mock_client = MagicMock()
        chunks = ["Hello! ", "I am ", "Kratos, ", "ready to help."]
        
        def fake_generate(model, messages, system_instruction, tools=None, on_chunk=None):
            if on_chunk:
                for c in chunks:
                    on_chunk(c)
            return "".join(chunks)

        mock_client.generate.side_effect = fake_generate
        adapter = KratosModelAdapter("test-model", mock_client)

        streamed = []
        resp = adapter.complete(
            {"messages": [{"role": "user", "content": "hello"}]},
            on_chunk=streamed.append,
        )

        self.assertEqual("".join(streamed), "Hello! I am Kratos, ready to help.")
        self.assertEqual(resp.text, "Hello! I am Kratos, ready to help.")
        self.assertEqual(resp.tool_calls, [])

    def test_agent_loop_emits_model_chunk(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            ws = Path(tmp_dir)
            emitted_events = []

            def fake_emit(event):
                emitted_events.append(event)

            class StreamingFakeModel:
                def complete(self, request, on_chunk=None):
                    if on_chunk:
                        on_chunk("Chunk 1 ")
                        on_chunk("Chunk 2")
                    return ModelResponse(text="Chunk 1 Chunk 2")

            loop = AgentLoop(
                context=ContextBuilder(ContextBudget()),
                instructions=InstructionEngine(),
                tools=ToolRegistry(),
                model=StreamingFakeModel(),
                emit=fake_emit,
                workspace=ws,
            )

            from kratos_agent.core.runtime_contracts import ChatMessage
            history = [ChatMessage("user", "how are you")]
            reply, final_history = loop.run(history, lambda spec, args: (True, "ok"))

            chunk_events = [e for e in emitted_events if e.kind == EventKind.MODEL_CHUNK]
            self.assertEqual(len(chunk_events), 2)
            self.assertEqual(chunk_events[0].payload["chunk"], "Chunk 1 ")
            self.assertEqual(chunk_events[1].payload["chunk"], "Chunk 2")
            self.assertEqual(reply, "Chunk 1 Chunk 2")

    def test_event_renderer_stream_text_accumulation(self):
        renderer = EventRenderer(is_tty=True)
        self.assertEqual(renderer.stream_text, "")

        renderer.on_model_chunk("Streaming ")
        renderer.on_model_chunk("token response")
        self.assertEqual(renderer.stream_text, "Streaming token response")

        # Reset clears it
        renderer.reset()
        self.assertEqual(renderer.stream_text, "")

    def test_live_renderer_renders_stream_panel(self):
        runtime_mock = MagicMock()
        runtime_mock.model_name = "gemini-3.7-flash-high"
        tui = KratosLiveRenderer(runtime_mock)

        # Emit model chunk
        tui._hooked_emit(RuntimeEvent(EventKind.MODEL_CHUNK, {"chunk": "Live response token"}, "t1"))
        self.assertEqual(tui._renderer.stream_text, "Live response token")

        # Verify build_renderable includes the streaming panel
        renderable = tui._build_renderable()
        self.assertIsNotNone(renderable)


if __name__ == "__main__":
    unittest.main()
