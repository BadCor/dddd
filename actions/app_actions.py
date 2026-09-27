"""Allowlist-based application launcher."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping

from . import windows
from .result import ActionResult
from core.errors import ErrorCategory, error_info

logger = logging.getLogger(__name__)


def launch_application(name: str, apps: Mapping[str, Any]) -> ActionResult:
    action = "launch_application"
    if not isinstance(name, str) or not name.strip():
        return ActionResult(False, action, error="Application name must be a non-empty string.")

    key = name.strip()
    configured = {str(k).casefold(): v for k, v in apps.items()} if isinstance(apps, Mapping) else {}
    if key.casefold() not in configured:
        logger.warning("Rejected unapproved application request.")
        return ActionResult(False, action, error="Application is not approved/configured.")

    target = configured[key.casefold()]
    if not isinstance(target, str) or not target.strip():
        return ActionResult(False, action, error="Configured application path is invalid.")
    target_path = Path(target)

    try:
        if not target_path.exists():
            return ActionResult(False, action, error="Configured application does not exist.")
        if not target_path.is_file():
            return ActionResult(False, action, error="Configured application path is not a file.")
        windows.launch_configured_application(target_path)
    except PermissionError:
        logger.warning("Permission denied launching configured application.")
        return ActionResult(False, action, error="Permission denied.")
    except OSError as exc:
        logger.warning("OS failure launching configured application: %s", exc)
        return ActionResult(False, action, error="Could not launch application.")
    except Exception as exc:
        logger.error("Unexpected application launch failure (%s).", type(exc).__name__)
        return ActionResult(False, action, error="Could not launch application safely.", error_info=error_info(exc, category=ErrorCategory.ACTION, user_message="Could not launch application safely."))

    logger.info("Launched approved application successfully.")
    return ActionResult(True, action, message="Application launched successfully.")
