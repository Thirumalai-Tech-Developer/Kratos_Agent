import unittest

from benchmarks.kratos_harbor_fast_agent import KratosHarborFastAgent


class FastBenchmarkAdapterTests(unittest.TestCase):
    def test_adapter_identity(self):
        self.assertEqual(KratosHarborFastAgent.name(), "kratos-fast")
        self.assertEqual(KratosHarborFastAgent.version(), "0.2.0")


if __name__ == "__main__":
    unittest.main()
