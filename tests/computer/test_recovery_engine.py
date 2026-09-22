"""Tests for RecoveryEngine failure classification and ladder."""
import unittest
from kratos_agent.computer.state import ComputerAction, ActionResult
from kratos_agent.computer.recovery import RecoveryEngine
from kratos_agent.computer.gui.errors import (
    FailureType,
    TargetNotFoundError,
    AmbiguousTargetError,
    ElementDisabledError,
)


class TestRecoveryEngine(unittest.TestCase):
    def test_failure_classification(self):
        engine = RecoveryEngine()

        self.assertEqual(engine.classify_failure(TargetNotFoundError("not found")), FailureType.TARGET_NOT_FOUND)
        self.assertEqual(engine.classify_failure(AmbiguousTargetError("ambiguous")), FailureType.AMBIGUOUS_TARGET)
        self.assertEqual(engine.classify_failure(ElementDisabledError("disabled")), FailureType.ELEMENT_DISABLED)
        self.assertEqual(engine.classify_failure("Action timed out after 10s"), FailureType.TIMEOUT)
        self.assertEqual(engine.classify_failure("Access denied / permission denied"), FailureType.PERMISSION_DENIED)

    def test_recovery_ladder_success_on_attempt_3(self):
        engine = RecoveryEngine()
        attempts_seen = []

        def mock_executor(action: ComputerAction, attempt: int) -> ActionResult:
            attempts_seen.append(attempt)
            if attempt < 3:
                return ActionResult(ok=False, action=action.action, detail="Failed")
            return ActionResult(ok=True, action=action.action, detail="Recovered via keyboard", method_used="keyboard")

        action = ComputerAction(action="click", target={"name": "Submit"})
        res = engine.execute_with_recovery(action, mock_executor)
        self.assertTrue(res.ok)
        self.assertEqual(attempts_seen, [1, 2, 3])
        self.assertEqual(res.method_used, "keyboard")


if __name__ == "__main__":
    unittest.main()
