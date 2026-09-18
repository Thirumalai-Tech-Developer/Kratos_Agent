"""Unit tests for Headroom Context Compression integration in Kratos Agent.

Tests graceful degradation, plugin lifecycle, stats tracking,
context pipeline integration, and compactor integration.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from kratos_agent.brain.config import (
    get_headroom_model,
    get_headroom_proxy_port,
    is_headroom_enabled,
)
from kratos_agent.core.compactor import ConversationCompactor, _try_headroom_compress
from kratos_agent.core.context_pipeline import (
    ContextBudget,
    ContextBuilder,
    detect_content_type,
    headroom_compress_text,
)
from kratos_agent.core.harness.kernel import HarnessKernel
from kratos_agent.core.harness.plugins.headroom_plugin import (
    HeadroomPlugin,
    HeadroomStats,
    is_headroom_available,
)


class TestHeadroomStats(unittest.TestCase):
    """Test HeadroomStats dataclass and calculation methods."""

    def test_initial_stats(self):
        stats = HeadroomStats()
        self.assertEqual(stats.total_calls, 0)
        self.assertEqual(stats.total_input_tokens, 0)
        self.assertEqual(stats.total_output_tokens, 0)
        self.assertEqual(stats.total_tokens_saved, 0)
        self.assertEqual(stats.overall_ratio, 0.0)
        self.assertEqual(stats.savings_percent, 0.0)
        self.assertTrue(stats.enabled)

    def test_savings_calculation(self):
        stats = HeadroomStats(
            total_calls=5,
            total_input_tokens=1000,
            total_output_tokens=600,
            total_tokens_saved=400,
        )
        self.assertAlmostEqual(stats.overall_ratio, 0.4)
        self.assertEqual(stats.savings_percent, 40.0)

    def test_to_dict(self):
        stats = HeadroomStats(
            total_calls=2,
            total_input_tokens=500,
            total_output_tokens=300,
            total_tokens_saved=200,
            per_content_type={"json": 150, "log": 50},
        )
        d = stats.to_dict()
        self.assertEqual(d["total_calls"], 2)
        self.assertEqual(d["total_tokens_saved"], 200)
        self.assertEqual(d["savings_percent"], 40.0)
        self.assertEqual(d["per_content_type"], {"json": 150, "log": 50})
        self.assertTrue(d["enabled"])


class TestHeadroomPlugin(unittest.TestCase):
    """Test HeadroomPlugin lifecycle, config, and compression methods."""

    def test_plugin_metadata(self):
        plugin = HeadroomPlugin()
        self.assertEqual(plugin.name, "headroom")
        self.assertIn("compression", plugin.metadata.tags)

    def test_plugin_lifecycle_without_headroom(self):
        plugin = HeadroomPlugin()
        kernel = HarnessKernel()
        plugin.on_load(kernel)

        with patch("kratos_agent.core.harness.plugins.headroom_plugin.is_headroom_available", return_value=False):
            plugin.on_enable()
            self.assertFalse(plugin.available)
            self.assertIsNone(kernel.get_service("headroom"))

        plugin.on_disable()
        self.assertFalse(plugin.available)

    def test_plugin_lifecycle_with_mocked_headroom(self):
        plugin = HeadroomPlugin()
        kernel = HarnessKernel()
        plugin.on_load(kernel)

        mock_compress = MagicMock()

        with patch("kratos_agent.core.harness.plugins.headroom_plugin.is_headroom_available", return_value=True):
            with patch.dict("sys.modules", {"headroom": MagicMock(compress=mock_compress)}):
                plugin.on_enable()
                self.assertTrue(plugin.available)
                self.assertIsNotNone(kernel.get_service("headroom"))

                # Test toggle off
                plugin.toggle(False)
                self.assertFalse(plugin.available)

                # Test toggle on
                plugin.toggle(True)
                self.assertTrue(plugin.available)

                # Test on_disable
                plugin.on_disable()
                self.assertFalse(plugin.available)
                self.assertIsNone(kernel.get_service("headroom"))

    def test_compress_messages_graceful_fallback(self):
        plugin = HeadroomPlugin()
        msgs = [{"role": "user", "content": "Hello world"}]
        # When unavailable
        result_msgs, stats = plugin.compress_messages(msgs)
        self.assertEqual(result_msgs, msgs)
        self.assertFalse(stats["compressed"])

    def test_compress_text_too_short(self):
        plugin = HeadroomPlugin()
        short_text = "Short string"
        result, stats = plugin.compress_text(short_text)
        self.assertEqual(result, short_text)
        self.assertFalse(stats["compressed"])

    def test_compress_text_with_mock(self):
        plugin = HeadroomPlugin()
        long_text = "x" * 300

        mock_result = MagicMock()
        mock_result.tokens_saved = 50
        mock_result.compression_ratio = 0.4
        mock_result.original_tokens = 125
        mock_result.messages = [{"role": "user", "content": "compressed_result"}]

        plugin._compress_fn = MagicMock(return_value=mock_result)

        compressed, stats = plugin.compress_text(long_text, content_type="json")
        self.assertEqual(compressed, "compressed_result")
        self.assertTrue(stats["compressed"])
        self.assertEqual(stats["tokens_saved"], 50)
        self.assertEqual(plugin.stats.total_tokens_saved, 50)
        self.assertEqual(plugin.stats.per_content_type.get("json"), 50)


class TestContextPipelineHeadroom(unittest.TestCase):
    """Test Headroom integration in context_pipeline.py."""

    def test_detect_content_type(self):
        self.assertEqual(detect_content_type('{"status": "ok"}'), "json")
        self.assertEqual(detect_content_type('[1, 2, 3]'), "json")
        self.assertEqual(detect_content_type("2026-09-18 ERROR Connection refused"), "log")
        self.assertEqual(detect_content_type("Traceback (most recent call last):"), "log")
        self.assertEqual(detect_content_type("def calculate_total(x, y):"), "code")
        self.assertEqual(detect_content_type("class MyService:"), "code")
        self.assertEqual(detect_content_type("This is just standard plain text."), "text")

    def test_headroom_compress_text_fallback(self):
        result, stats = headroom_compress_text("sample content")
        self.assertEqual(result, "sample content")

    def test_prune_tool_result_without_headroom(self):
        budget = ContextBudget(max_tool_result_chars=100)
        builder = ContextBuilder(budget=budget)

        # Short text should remain unchanged
        short_text = "Hello world"
        result, compressed = builder.prune_tool_result(short_text)
        self.assertEqual(result, short_text)
        self.assertFalse(compressed)

        # Long text exceeds 100 chars, should be truncated with omission message
        long_text = "\n".join(f"Line {i}" for i in range(100))
        result, compressed = builder.prune_tool_result(long_text)
        self.assertTrue(compressed)
        self.assertIn("lines omitted", result)


class TestCompactorHeadroom(unittest.TestCase):
    """Test Headroom integration in compactor.py."""

    def test_try_headroom_compress_fallback(self):
        sample = "Short text"
        result = _try_headroom_compress(sample)
        self.assertEqual(result, sample)

    def test_compress_heuristic_preserves_messages(self):
        compactor = ConversationCompactor(max_turns=4, keep_recent_turns=2)
        older = [
            {"role": "user", "content": "Please implement the new feature."},
            {"role": "assistant", "content": "I have created the files and updated the tests."},
        ]
        summary = compactor.compress_heuristic(older)
        self.assertIn("[COMPACTED CONVERSATION CHECKPOINT]", summary)
        self.assertIn("Please implement the new feature.", summary)


class TestBrainConfigHeadroom(unittest.TestCase):
    """Test Headroom config helper functions."""

    def test_is_headroom_enabled_default(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertTrue(is_headroom_enabled())

    def test_is_headroom_enabled_custom(self):
        with patch.dict("os.environ", {"HEADROOM_ENABLED": "false"}):
            self.assertFalse(is_headroom_enabled())
        with patch.dict("os.environ", {"HEADROOM_ENABLED": "true"}):
            self.assertTrue(is_headroom_enabled())
        with patch.dict("os.environ", {"HEADROOM_ENABLED": "0"}):
            self.assertFalse(is_headroom_enabled())

    def test_get_headroom_model(self):
        with patch.dict("os.environ", {"HEADROOM_MODEL": "claude-3-5-sonnet"}):
            self.assertEqual(get_headroom_model(), "claude-3-5-sonnet")
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(get_headroom_model(), "gpt-4o")

    def test_get_headroom_proxy_port(self):
        with patch.dict("os.environ", {"HEADROOM_PROXY_PORT": "8787"}):
            self.assertEqual(get_headroom_proxy_port(), 8787)
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(get_headroom_proxy_port())


if __name__ == "__main__":
    unittest.main()
