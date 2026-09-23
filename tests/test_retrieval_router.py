"""Unit tests for Unified RetrievalRouter (web, tools, github, all)."""
import asyncio
import unittest

from kratos_agent.retrieval import (
    RetrievalQuery,
    RetrievalResult,
    get_retrieval_router,
)


class TestRetrievalRouter(unittest.TestCase):

    def setUp(self):
        self.router = get_retrieval_router()

    def test_retrieve_tools(self):
        async def _run():
            res = await self.router.retrieve(RetrievalQuery(text="open Chrome and navigate", target="tools", max_results=5))
            self.assertEqual(res.target, "tools")
            self.assertGreaterEqual(res.total, 1)
            self.assertLessEqual(res.total, 5)
        asyncio.run(_run())

    def test_retrieve_web(self):
        async def _run():
            res = await self.router.retrieve(RetrievalQuery(text="Python programming", target="web", max_results=3))
            self.assertEqual(res.target, "web")
            self.assertGreaterEqual(res.total, 1)
        asyncio.run(_run())

    def test_retrieve_github(self):
        async def _run():
            res = await self.router.retrieve(RetrievalQuery(text="cpython", target="github", max_results=2))
            self.assertEqual(res.target, "github")
            self.assertGreaterEqual(res.total, 1)
        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
