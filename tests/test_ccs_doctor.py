import json
import unittest
from kratos_agent.ccs.doctor import DoctorRunner

class TestCcsDoctor(unittest.TestCase):
    def test_doctor_json_mode(self):
        runner = DoctorRunner(json_mode=True)
        code = runner.run_all()
        self.assertEqual(code, 0, "Doctor should pass all live capability tests")
        records = runner.records
        self.assertIsInstance(records, list)
        self.assertGreaterEqual(len(records), 25)

        for r in records:
            self.assertTrue(r.passed, f"Test failed in doctor: {r}")

if __name__ == "__main__":
    unittest.main()
