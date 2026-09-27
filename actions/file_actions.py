"""Validated file/folder actions."""

from __future__ import annotations

import logging
from pathlib import Path

from .result import ActionResult
from core.errors import ErrorCategory, error_info
from . import windows

logger = logging.getLogger(__name__)


def open_file(path: str) -> ActionResult:
    action = "open_file"
    try:
        target = Path(path)
        if not target.exists():
            return ActionResult(False, action, error="File does not exist.")
        if not target.is_file():
            return ActionResult(False, action, error="Path is not a file.")
        windows.open_path(target)
    except PermissionError:
        logger.warning("Permission denied while opening file.")
        return ActionResult(False, action, error="Permission denied.")
    except OSError as exc:
        logger.warning("OS failure while opening file: %s", exc)
        return ActionResult(False, action, error="Could not open file.")
    except Exception as exc:
        logger.error("Unexpected file-open failure (%s).", type(exc).__name__)
        return ActionResult(False, action, error="Could not open file safely.", error_info=error_info(exc, category=ErrorCategory.ACTION, user_message="Could not open file safely."))

    logger.info("Opened file successfully.")
    return ActionResult(True, action, message="File opened successfully.")


def open_folder(path: str) -> ActionResult:
    action = "open_folder"
    try:
        target = Path(path)
        if not target.exists():
            return ActionResult(False, action, error="Folder does not exist.")
        if not target.is_dir():
            return ActionResult(False, action, error="Path is not a folder.")
        windows.open_path(target)
    except PermissionError:
        logger.warning("Permission denied while opening folder.")
        return ActionResult(False, action, error="Permission denied.")
    except OSError as exc:
        logger.warning("OS failure while opening folder: %s", exc)
        return ActionResult(False, action, error="Could not open folder.")
    except Exception as exc:
        logger.error("Unexpected folder-open failure (%s).", type(exc).__name__)
        return ActionResult(False, action, error="Could not open folder safely.", error_info=error_info(exc, category=ErrorCategory.ACTION, user_message="Could not open folder safely."))

    logger.info("Opened folder successfully.")
    return ActionResult(True, action, message="Folder opened successfully.")
