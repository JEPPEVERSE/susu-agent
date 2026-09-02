"""Application logging configuration.

All application loggers should be named ``susu_agent`` or one of its children.
This keeps application diagnostics in one place without changing the global
logging configuration of libraries used by the agent SDK.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


APP_LOGGER_NAME = "susu_agent"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_DIRECTORY = PROJECT_ROOT / "logs"
APPLICATION_LOG_FILENAME = "susu-agent.log"
ERROR_LOG_FILENAME = "susu-agent-error.log"
LOG_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)s | "
    "pid=%(process)d | %(message)s"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 7


def _get_log_level(level_name: str, default: int = logging.INFO) -> int:
    level = getattr(logging, level_name.strip().upper(), None)
    return level if isinstance(level, int) else default


def _get_positive_int(value: str | None, default: int) -> int:
    try:
        parsed_value = int(value) if value is not None else default
    except ValueError:
        return default
    return parsed_value if parsed_value > 0 else default


def _is_enabled(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def get_log_directory(configured_directory: str | Path | None = None) -> Path:
    """Resolve the configured log directory relative to the project root."""
    directory = Path(
        configured_directory
        if configured_directory is not None
        else os.getenv("LOG_DIR", str(DEFAULT_LOG_DIRECTORY))
    ).expanduser()
    return directory if directory.is_absolute() else PROJECT_ROOT / directory


def _new_file_handler(
    log_path: Path,
    level: int,
    formatter: logging.Formatter,
) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        log_path,
        maxBytes=_get_positive_int(
            os.getenv("LOG_MAX_BYTES"),
            DEFAULT_MAX_BYTES,
        ),
        backupCount=_get_positive_int(
            os.getenv("LOG_BACKUP_COUNT"),
            DEFAULT_BACKUP_COUNT,
        ),
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(formatter)
    return handler


def configure_logging(
    *,
    log_dir: str | Path | None = None,
    log_to_file: bool | None = None,
) -> logging.Logger:
    """Configure and return the application logger.

    ``LOG_LEVEL`` controls the console threshold; ``LOG_FILE_LEVEL`` controls
    the complete application log and defaults to ``DEBUG``. File logging is
    enabled by default, writes UTF-8 files under ``logs/``, and rotates files
    when they reach ``LOG_MAX_BYTES`` (10 MiB by default). The latest error
    entries are also retained in a dedicated error log.

    Repeated calls replace the application's previous handlers, which makes
    the function safe for tests and reload-based development.
    """
    logger = logging.getLogger(APP_LOGGER_NAME)
    # Let handlers determine their own threshold so file logging can retain
    # DEBUG diagnostics while the terminal remains concise.
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(_get_log_level(os.getenv("LOG_LEVEL", "INFO")))
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    should_log_to_file = (
        _is_enabled(os.getenv("LOG_TO_FILE"), default=True)
        if log_to_file is None
        else log_to_file
    )
    if should_log_to_file:
        resolved_log_dir = get_log_directory(log_dir)
        resolved_log_dir.mkdir(parents=True, exist_ok=True)
        file_level = _get_log_level(
            os.getenv("LOG_FILE_LEVEL", "DEBUG"),
            default=logging.DEBUG,
        )
        logger.addHandler(
            _new_file_handler(
                resolved_log_dir / APPLICATION_LOG_FILENAME,
                file_level,
                formatter,
            )
        )
        logger.addHandler(
            _new_file_handler(
                resolved_log_dir / ERROR_LOG_FILENAME,
                logging.ERROR,
                formatter,
            )
        )

    return logger
