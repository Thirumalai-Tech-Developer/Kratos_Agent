import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kratos_agent.core.verification_manager import VerificationManager


class AuthoritativeVerificationTests(unittest.TestCase):
    def test_discovers_existing_pytest_suite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "tests" / "test_existing.py").write_text("def test_ok(): pass\n", encoding="utf-8")
            manager = VerificationManager(root)
            commands = manager._candidate_test_commands()
            self.assertTrue(any(label == "pytest" for label, _ in commands))

    def test_runs_existing_suite_and_fails_on_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"scripts":{"test":"pytest"}}', encoding="utf-8")
            manager = VerificationManager(root)
            with patch("kratos_agent.core.verification_manager.subprocess.run") as run:
                run.return_value.returncode = 1
                run.return_value.stdout = "official test failed"
                passed, details = manager._run_discovered_tests(changed_files=["app.py"])
            self.assertFalse(passed)
            self.assertTrue(any("Authoritative project tests FAILED" in item for item in details))

    def test_self_authored_verify_file_is_not_an_authoritative_discovery_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "verify.py").write_text("print('ok')\n", encoding="utf-8")
            manager = VerificationManager(root)
            self.assertEqual(manager._candidate_test_commands(), [])


if __name__ == "__main__":
    unittest.main()
