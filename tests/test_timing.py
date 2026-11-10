import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from timing import measure


class TimingTest(unittest.TestCase):
    def test_success_duration(self):
        with patch("timing.perf_counter", side_effect=[10, 12.25]), self.assertLogs(
            "minimal_chat.timing", level="INFO"
        ) as logs:
            with measure("academicai_request"):
                pass
        self.assertIn("academicai_request duration=2.250s outcome=ok", logs.output[0])

    def test_failure_is_measured_without_logging_private_exception_text(self):
        error = ValueError("private prompt and credentials")
        with patch("timing.perf_counter", side_effect=[10, 13]), self.assertLogs(
            "minimal_chat.timing", level="INFO"
        ) as logs:
            with self.assertRaises(ValueError) as caught:
                with measure("session_save"):
                    raise error
        self.assertIs(caught.exception, error)
        self.assertIn("session_save duration=3.000s outcome=ValueError", logs.output[0])
        self.assertNotIn("private", logs.output[0])


if __name__ == "__main__":
    unittest.main()
