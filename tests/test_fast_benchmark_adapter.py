import unittest
from pathlib import Path

from benchmarks.kratos_harbor_fast_agent import KratosHarborFastAgent
from benchmarks.run_terminal_bench_fast import _build_harbor_command


class FastBenchmarkAdapterTests(unittest.TestCase):
    def test_adapter_identity(self):
        self.assertEqual(KratosHarborFastAgent.name(), "kratos-fast")
        self.assertEqual(KratosHarborFastAgent.version(), "0.3.0")

    def test_benchmark_command_sets_independent_verifier_timeout(self):
        command = _build_harbor_command(
            task="terminal-bench/html-js-filter",
            model="gemini/gemma-4-26b-a4b-it",
            jobs_dir=Path("benchmarks/jobs"),
            run_id="test-run",
            agent_timeout_multiplier=1 / 6,
            verifier_timeout_multiplier=2.0,
        )
        self.assertIn("--agent-timeout-multiplier", command)
        self.assertEqual(command[command.index("--agent-timeout-multiplier") + 1], str(1 / 6))
        self.assertIn("--verifier-timeout-multiplier", command)
        self.assertEqual(command[command.index("--verifier-timeout-multiplier") + 1], "2.0")


if __name__ == "__main__":
    unittest.main()
