import unittest

from benchmarks.kratos_harbor_agent import KratosHarborAgent


class KratosHarborAgentTests(unittest.TestCase):
    def test_explicit_app_deliverables_are_deduplicated_and_trimmed(self):
        self.assertEqual(
            KratosHarborAgent._requested_app_paths(
                "Create `/app/filter.py`, then verify /app/filter.py."
            ),
            ["/app/filter.py"],
        )


if __name__ == "__main__":
    unittest.main()
