import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from local_web.server import TutorWebRuntime


class LocalWebV02Tests(unittest.TestCase):
    def test_bootstrap_exposes_v02_artifacts_and_student_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            database = str(Path(temp_directory) / "web.db")
            with patch.dict(
                os.environ,
                {
                    "SESSION_DB_PATH": database,
                    "STUDENT_ID": "web_test_student",
                    "COURSE_SUBJECT": "math",
                },
            ):
                runtime = TutorWebRuntime()
                try:
                    payload = runtime._bootstrap_unlocked(include_messages=False)
                finally:
                    runtime.close()

        self.assertEqual(payload["v02_runtime"]["architecture_version"], "0.2")
        self.assertFalse(payload["v02_runtime"]["solution_ready"])
        self.assertFalse(payload["v02_runtime"]["verification_ready"])
        self.assertFalse(payload["v02_runtime"]["strategy_ready"])
        self.assertEqual(payload["teaching_state"]["schema_version"], 5)
        self.assertEqual(payload["student_model"]["student_id"], "web_test_student")


if __name__ == "__main__":
    unittest.main()
