import logging
import os


APP_LOGGER_NAME = "susu_agent"
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
def _get_log_level(level_name: str) -> int:
    level = getattr(logging, level_name.strip().upper(), None)
    return level if isinstance(level, int) else logging.INFO


def configure_logging() -> logging.Logger:
    """
    Configure and return the application's console logger.

    LOG_LEVEL controls the minimum level. Calling this function more than once
    replaces existing handlers instead of duplicating log lines.
    """
    logger = logging.getLogger(APP_LOGGER_NAME)
    logger.setLevel(_get_log_level(os.getenv("LOG_LEVEL", "INFO")))
    logger.propagate = False

    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger