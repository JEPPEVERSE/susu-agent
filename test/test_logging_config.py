import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from logging_config import (
    APPLICATION_LOG_FILENAME,
    ERROR_LOG_FILENAME,
    configure_logging,
)


class LoggingConfigurationTests(unittest.TestCase):
    def tearDown(self) -> None:
        configure_logging(log_to_file=False)

    def test_writes_utf8_application_and_error_logs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            logger = configure_logging(log_dir=temporary_directory, log_to_file=True)
            logger.debug("debug diagnostic")
            logger.info("中文日志")
            logger.error("error diagnostic")

            for handler in logger.handlers:
                handler.flush()

            log_directory = Path(temporary_directory)
            application_log = (
                log_directory / APPLICATION_LOG_FILENAME
            ).read_text(encoding="utf-8")
            error_log = (log_directory / ERROR_LOG_FILENAME).read_text(
                encoding="utf-8"
            )
            configure_logging(log_to_file=False)

        self.assertIn("debug diagnostic", application_log)
        self.assertIn("中文日志", application_log)
        self.assertIn("error diagnostic", error_log)
        self.assertNotIn("debug diagnostic", error_log)

    def test_reconfiguration_does_not_duplicate_handlers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            logger = configure_logging(log_dir=temporary_directory, log_to_file=True)
            configure_logging(log_dir=temporary_directory, log_to_file=True)

            self.assertEqual(len(logger.handlers), 3)
            configure_logging(log_to_file=False)


if __name__ == "__main__":
    unittest.main()
