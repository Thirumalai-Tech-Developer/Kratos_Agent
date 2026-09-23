import json
import tempfile
import unittest
from pathlib import Path

from kratos_agent.computer.browser.intent import parse_media_intent
from kratos_agent.memory.models import MemoryRecord
from kratos_agent.memory.store import MemoryStore
from kratos_agent.search.tavily import TavilySearchProvider


class TestAutonomyRegressions(unittest.TestCase):
    def test_whatsapp_message_intent_is_not_open_only(self):
        intent = parse_media_intent('open whatsapp and chat with தமிழ். send "hii" to him')
        self.assertNotEqual(intent.get("intent"), "open_whatsapp")

    def test_whatsapp_message_extracts_contact_from_tail_language_clarification(self):
        intent = parse_media_intent('can open whatsappweb and send msg hi to thirumalai the contact may be in tail language')
        self.assertEqual(intent.get("intent"), "whatsapp_message")
        self.assertEqual(intent.get("contact"), "thirumalai")
        self.assertEqual(intent.get("message"), "hi")

    def test_memory_add_is_persistent(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "memory.json"
            store = MemoryStore(storage_path=path)
            store.add(MemoryRecord(content="Reuse the existing WhatsApp session", importance=0.9, confidence=0.95))
            self.assertTrue(path.exists())
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(payload.get("records", [])), 1)

    def test_tavily_provider_requires_key_without_network_call(self):
        provider = TavilySearchProvider(api_key="")
        self.assertFalse(provider.configured)


if __name__ == "__main__":
    unittest.main()
