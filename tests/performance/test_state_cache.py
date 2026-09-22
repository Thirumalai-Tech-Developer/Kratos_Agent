"""Unit tests for StateCache and state-aware observation."""
from __future__ import annotations
import time
import unittest

from kratos_agent.computer.state import ComputerState
from kratos_agent.computer.state_cache import StateCache


class TestStateCache(unittest.TestCase):
    def setUp(self) -> None:
        self.cache = StateCache(ttl_seconds=2.0)

    def test_quick_hash_computation(self) -> None:
        h1 = self.cache.compute_quick_hash("Google Chrome", 5, "https://google.com")
        h2 = self.cache.compute_quick_hash("Google Chrome", 5, "https://google.com")
        h3 = self.cache.compute_quick_hash("Visual Studio Code", 5, None)

        self.assertEqual(h1, h2)
        self.assertNotEqual(h1, h3)

    def test_cache_hit_and_miss(self) -> None:
        call_count = [0]

        def fake_observe() -> ComputerState:
            call_count[0] += 1
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
                interactive_elements=[{"id": "btn1", "name": "Search"}],
                generation=call_count[0],
                timestamp=time.time(),
            )

        quick_hash = self.cache.compute_quick_hash("Chrome", 1, "https://google.com")

        # First call: cache miss
        st1, hit1 = self.cache.get_or_observe(fake_observe, quick_hash)
        self.assertFalse(hit1)
        self.assertEqual(call_count[0], 1)
        self.assertEqual(self.cache.cache_misses, 1)
        self.assertEqual(self.cache.cache_hits, 0)

        # Second call with identical state: cache hit
        st2, hit2 = self.cache.get_or_observe(fake_observe, quick_hash)
        self.assertTrue(hit2)
        self.assertEqual(call_count[0], 1)  # No re-observation!
        self.assertEqual(self.cache.cache_hits, 1)
        self.assertEqual(st1, st2)

        # Invalidation forces re-observation
        self.cache.invalidate()
        st3, hit3 = self.cache.get_or_observe(fake_observe, quick_hash)
        self.assertFalse(hit3)
        self.assertEqual(call_count[0], 2)
        self.assertEqual(self.cache.cache_misses, 2)

    def test_ttl_expiration(self) -> None:
        short_cache = StateCache(ttl_seconds=0.1)
        call_count = [0]

        def fake_observe() -> ComputerState:
            call_count[0] += 1
            return ComputerState(
                platform="windows",
                desktop="main",
                active_window=None,
                windows=[],
                applications=[],
                focused_element=None,
                clipboard="",
                screen_size=(1920, 1080),
                browser_state={},
                capabilities={},
                interactive_elements=[],
                generation=call_count[0],
                timestamp=time.time(),
            )

        h = short_cache.compute_quick_hash("", 0, None)
        short_cache.get_or_observe(fake_observe, h)
        self.assertEqual(call_count[0], 1)

        # Sleep past TTL
        time.sleep(0.15)
        short_cache.get_or_observe(fake_observe, h)
        self.assertEqual(call_count[0], 2)


if __name__ == "__main__":
    unittest.main()
