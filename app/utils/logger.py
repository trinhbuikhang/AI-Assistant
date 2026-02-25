"""Application logging setup. All errors and important events logged to app.log with full traceback."""

import logging
import sys
from pathlib import Path


class _FileFormatter(logging.Formatter):
    """Formatter that appends exception traceback to the log file when present."""

    def format(self, record):
        s = super().format(record)
        if record.exc_info:
            s += "\n" + self.formatException(record.exc_info)
        return s


def setup_logger(name: str = "ai_assistant", log_dir: str | None = None) -> logging.Logger:
    """Configure and return the application logger. Writes to app.log and stderr. logger.exception() records full traceback to app.log."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    base_fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    if log_dir is None:
        log_dir = Path(__file__).resolve().parent.parent.parent
    log_path = Path(log_dir) / "app.log"

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(_FileFormatter(base_fmt, datefmt=datefmt))
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(base_fmt, datefmt=datefmt))
    logger.addHandler(console_handler)

    return logger
