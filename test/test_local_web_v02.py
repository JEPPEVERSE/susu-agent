import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from local_web.server import TutorWebRuntime


class LocalWebV03Tests(unittest.TestCase):
    def test_expression_failure_returns_latest_state_without_internal_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            database = str(Path(temp_directory) / "web.db")
            with patch.dict(os.environ, {"SESSION_DB_PATH": database}):
                runtime = TutorWebRuntime()
                try:
                    with patch.object(
                        runtime,
                        "_ask_async",
                        new=AsyncMock(side_effect=RuntimeError("private details")),
                    ):
                        payload = runtime.ask("测试题")
                finally:
                    runtime.close()

        self.assertTrue(payload["degraded"])
        self.assertIn("重新发送", payload["answer"])
        self.assertNotIn("private details", payload["answer"])
        self.assertIn("teaching_state", payload)

    def test_bootstrap_exposes_v03_artifacts_and_student_model(self) -> None:
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

        self.assertEqual(payload["v03_runtime"]["architecture_version"], "0.3")
        self.assertFalse(payload["v03_runtime"]["solution_ready"])
        self.assertFalse(payload["v03_runtime"]["verification_ready"])
        self.assertFalse(payload["v03_runtime"]["strategy_ready"])
        self.assertEqual(payload["teaching_state"]["schema_version"], 7)
        self.assertNotIn("student_model", payload["teaching_state"])
        self.assertEqual(payload["student_model"]["student_id"], "web_test_student")


if __name__ == "__main__":
    unittest.main()
