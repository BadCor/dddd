"""
logger.py

Central logging setup. Every module gets its logger via
`logging.getLogger(__name__)` as usual; this file just configures the
root logger once, at startup, based on config values.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict

from .errors import redact_secrets
from .runtime_paths import is_frozen, user_data_root


class SecretRedactionFilter(logging.Filter):
    """Redact common credentials from every emitted log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = redact_secrets(record.getMessage())
            record.msg = message
            record.args = ()
        except Exception:
            record.msg = "Log message could not be safely rendered."
            record.args = ()
        return True



def setup_logging(project_root: Path, logging_config: Dict[str, Any]) -> logging.Logger:
    """
    Configure the root logger with a rotating file handler and, optionally,
    a console handler. Returns the configured root logger.

    Never raises on log-setup problems that can be worked around (e.g. an
    unwritable log directory falls back to console-only logging); only
    raises if logging cannot be set up at all.
    """
    level_name = logging_config.get("level", "INFO")
    level = getattr(logging, level_name, logging.INFO)

    log_dir_name = logging_config.get("log_dir", "logs")
    log_file_name = logging_config.get("log_file", "app.log")
    max_bytes = int(logging_config.get("max_bytes", 1_048_576))
    backup_count = int(logging_config.get("backup_count", 3))
    console_output = bool(logging_config.get("console_output", True))

    log_dir = (user_data_root() / log_dir_name) if is_frozen() else (Path(project_root) / log_dir_name)
    handlers: list[logging.Handler] = []

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler_ok = False
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / log_file_name,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(SecretRedactionFilter())
        handlers.append(file_handler)
        file_handler_ok = True
    except OSError:
        # We'll fall back to console-only and warn about it below,
        # once at least one handler exists.
        pass

    if console_output or not file_handler_ok:
        console_handler = logging.StreamHandler(stream=sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(SecretRedactionFilter())
        handlers.append(console_handler)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Avoid duplicate handlers if setup_logging() is called more than once
    # (e.g. in tests).
    root_logger.handlers.clear()
    for handler in handlers:
        root_logger.addHandler(handler)

    if not file_handler_ok:
        root_logger.warning(
            "Could not create log file in '%s'; logging to console only.", log_dir
        )

    return root_logger
