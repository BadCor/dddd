"""Safe HTTP(S) URL action."""

from __future__ import annotations

import logging

from .result import ActionResult
from core.errors import ErrorCategory, error_info
from core.exceptions import ActionValidationError
from . import windows
from .validators import validate_action

logger = logging.getLogger(__name__)


def open_url(url: str) -> ActionResult:
    action = "open_url"
    try:
        validate_action({"action": action, "target": url})
        windows.open_browser_url(url.strip())
    except ActionValidationError as exc:
        logger.warning("Rejected URL request: %s", exc)
        return ActionResult(False, action, error=str(exc))
    except PermissionError:
        return ActionResult(False, action, error="Permission denied.")
    except OSError as exc:
        logger.warning("OS/browser failure for URL: %s", exc)
        return ActionResult(False, action, error="Could not open URL.")
    except Exception as exc:
        logger.error("Unexpected URL action failure (%s).", type(exc).__name__)
        return ActionResult(False, action, error="Could not open URL safely.", error_info=error_info(exc, category=ErrorCategory.ACTION, user_message="Could not open URL safely."))

    logger.info("Opened URL successfully.")
    return ActionResult(True, action, message="URL opened successfully.")
