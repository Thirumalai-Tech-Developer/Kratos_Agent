import time
import unittest
from kratos_agent.ccs.perception.cache import PerceptionCache

class TestPerceptionCache(unittest.TestCase):
    def test_cache_hit_within_ttl(self):
        cache = PerceptionCache(ttl_ms=500)
        cache.set_frame("frame_1", b"data1")
        cached = cache.get_frame()
        self.assertIsNotNone(cached)
        self.assertEqual(cached.frame_ref, "frame_1")
        self.assertEqual(cached.data, b"data1")

    def test_cache_expiration_after_ttl(self):
        cache = PerceptionCache(ttl_ms=50) # 50 ms TTL
        cache.set_frame("frame_2", b"data2")
        time.sleep(0.06)  # Exceed 50 ms
        self.assertIsNone(cache.get_frame())

    def test_element_handles_and_invalidation(self):
        cache = PerceptionCache()
        cache.store_elements({"e1": {"name": "button1"}, "e2": {"name": "button2"}})
        self.assertEqual(cache.get_element("e1"), {"name": "button1"})
        cache.invalidate()
        self.assertIsNone(cache.get_element("e1"))
        self.assertIsNone(cache.get_frame())

if __name__ == "__main__":
    unittest.main()
