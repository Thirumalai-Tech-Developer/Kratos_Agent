"""Tests for SemanticResolver selector matching and ambiguity detection."""
import unittest
from kratos_agent.computer.gui.models import GUIElement
from kratos_agent.computer.gui.selectors import ElementSelector
from kratos_agent.computer.gui.resolver import SemanticResolver
from kratos_agent.computer.gui.errors import AmbiguousTargetError, TargetNotFoundError


class TestSemanticResolver(unittest.TestCase):
    def test_element_selector_exact_and_partial(self):
        elem = GUIElement(id="btn_save", name="Save File", role="button")

        sel_exact = ElementSelector(name="Save File", role="button")
        matched, score = sel_exact.matches(elem)
        self.assertTrue(matched)
        self.assertGreaterEqual(score, 0.8)

        sel_partial = ElementSelector(name="Save")
        matched, score = sel_partial.matches(elem)
        self.assertTrue(matched)
        self.assertGreaterEqual(score, 0.7)

        sel_wrong = ElementSelector(name="Cancel")
        matched, _ = sel_wrong.matches(elem)
        self.assertFalse(matched)

    def test_semantic_resolver_ambiguity_detection(self):
        resolver = SemanticResolver()

        # Two elements with identical high-confidence matching
        elem1 = GUIElement(id="btn_1", name="Submit Form", role="button", confidence=0.98)
        elem2 = GUIElement(id="btn_2", name="Submit Form", role="button", confidence=0.98)

        with self.assertRaises(AmbiguousTargetError):
            resolver.resolve({"name": "Submit Form", "role": "button"}, elements=[elem1, elem2])

    def test_semantic_resolver_single_candidate(self):
        resolver = SemanticResolver()
        elem = GUIElement(id="btn_ok", name="OK", role="button", confidence=0.98)
        res = resolver.resolve({"name": "OK"}, elements=[elem])
        self.assertEqual(res.id, "btn_ok")


if __name__ == "__main__":
    unittest.main()
