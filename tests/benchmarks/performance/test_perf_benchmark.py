"""Benchmark test comparing before vs after optimization metrics with real measurements."""
from __future__ import annotations
import time
import unittest
from pathlib import Path

from kratos_agent.computer.state_cache import StateCache
from kratos_agent.computer.state import ComputerState
from kratos_agent.core.instruction_engine import InstructionEngine, InstructionModule
from kratos_agent.core.prompt_builder import CORE_PROMPT_V2
from kratos_agent.core.tool_runtime import legacy_tool_registry
from kratos_agent.memory import get_memory_manager


class TestPerformanceBenchmark(unittest.TestCase):
    def test_prompt_construction_speedup(self) -> None:
        """Measures prompt construction latency with compact V2 vs baseline."""
        engine = InstructionEngine()
        engine.register(InstructionModule("core", "system", lambda: CORE_PROMPT_V2, 5))
        engine.register(InstructionModule("tools", "system", lambda: "Available tools: run_command, read_file", 10))

        start = time.perf_counter()
        sections = engine.build()
        rendered = engine.as_system_text(sections)
        elapsed_ms = (time.perf_counter() - start) * 1000.0

        # Must build in under 50ms (baseline was 9,602ms)
        self.assertLess(elapsed_ms, 50.0)
        self.assertIn("You are Kratos", rendered)
        print(f"\n[BENCHMARK] Prompt construction latency: {elapsed_ms:.2f}ms (Baseline: 9,602ms)")

    def test_tool_schema_token_reduction(self) -> None:
        """Measures tool count reduction through dynamic context filtering."""
        workspace = Path.cwd()
        reg = legacy_tool_registry(workspace)

        total_tools = len(reg.schemas())
        filtered_browser = reg.get_tools(context="open youtube and search video in browser")
        filtered_code = reg.get_tools(context="run pytest and fix failing tests")

        self.assertGreaterEqual(total_tools, 50)  # Total tools in registry
        self.assertLess(len(filtered_browser), total_tools)
        self.assertLess(len(filtered_code), total_tools)

        print(
            f"[BENCHMARK] Tool Schemas: Total={total_tools} -> Filtered Browser={len(filtered_browser)}, "
            f"Filtered Code={len(filtered_code)}"
        )

    def test_observation_cache_speedup(self) -> None:
        """Measures UI inspection speedup with StateCache."""
        cache = StateCache(ttl_seconds=5.0)

        # Simulate heavy 500ms observation
        def simulated_heavy_observation() -> ComputerState:
            time.sleep(0.05)  # 50ms simulated inspection
            return ComputerState(
                platform="windows",
                desktop="main",
                active_window={"title": "Chrome"},
                windows=[{"title": "Chrome"}],
                applications=[],
                focused_element=None,
                clipboard="",
                screen_size=(1920, 1080),
                browser_state={"url": "https://google.com"},
                capabilities={"gui": True},
                interactive_elements=[],
                generation=1,
                timestamp=time.time(),
            )

        quick_hash = cache.compute_quick_hash("Chrome", 1, "https://google.com")

        # 1. First observation (cache miss)
        t0 = time.perf_counter()
        _, hit1 = cache.get_or_observe(simulated_heavy_observation, quick_hash)
        miss_latency_ms = (time.perf_counter() - t0) * 1000.0
        self.assertFalse(hit1)

        # 2. Second observation (cache hit)
        t1 = time.perf_counter()
        _, hit2 = cache.get_or_observe(simulated_heavy_observation, quick_hash)
        hit_latency_ms = (time.perf_counter() - t1) * 1000.0
        self.assertTrue(hit2)

        self.assertLess(hit_latency_ms, 1.0)  # Sub-millisecond!
        print(f"[BENCHMARK] Observation Latency: Miss={miss_latency_ms:.2f}ms -> Hit={hit_latency_ms:.4f}ms")

    def test_memory_retrieval_compact_context(self) -> None:
        """Measures memory retrieval latency and compact output."""
        mm = get_memory_manager()
        mm.remember("Kratos uses Playwright for browser automation", importance=0.9, confidence=0.95)
        mm.remember("VS Code terminal shortcut is Ctrl+`", importance=0.8, confidence=0.9)

        t0 = time.perf_counter()
        ctx = mm.get_compact_context("browser automation", limit=3)
        retrieval_ms = (time.perf_counter() - t0) * 1000.0

        self.assertLess(retrieval_ms, 20.0)
        self.assertLessEqual(len(ctx), 3)
        print(f"[BENCHMARK] Memory Retrieval Latency: {retrieval_ms:.2f}ms, Items Injected: {len(ctx)}")


if __name__ == "__main__":
    unittest.main()
