"""Central Stage 2 action dispatcher."""

from __future__ import annotations

import logging
from typing import Any, Mapping

from core.exceptions import ActionValidationError
from core.errors import ErrorCategory, error_info, redact_secrets

from .app_actions import launch_application
from .file_actions import open_file, open_folder
from .result import ActionResult
from .url_actions import open_url
from .validators import ValidatedAction, validate_action

logger = logging.getLogger(__name__)


class ActionManager:
    """Validate and dispatch only the explicitly supported actions."""

    def __init__(self, apps: Mapping[str, Any] | None = None):
        self.apps = apps or {}

    def validate(self, raw_action: Any) -> ValidatedAction:
        return validate_action(raw_action)

    def execute(self, raw_action: Any) -> ActionResult:
        try:
            action = self.validate(raw_action)
        except ActionValidationError as exc:
            action_name = raw_action.get("action", "unknown") if isinstance(raw_action, Mapping) else "unknown"
            if not isinstance(action_name, str):
                action_name = "unknown"
            logger.warning("Action validation failed: %s", redact_secrets(exc))
            return ActionResult(False, action_name, error=str(exc), error_info=error_info(exc, category=ErrorCategory.VALIDATION, user_message=str(exc)))

        try:
            return self.execute_validated(action)
        except Exception as exc:  # defensive execution boundary
            logger.error("Unexpected action failure (%s).", type(exc).__name__)
            return ActionResult(False, action.action, error="Action could not be completed safely.", error_info=error_info(exc, category=ErrorCategory.ACTION, user_message="Action could not be completed safely."))

    def execute_validated(self, action: ValidatedAction) -> ActionResult:
        if not isinstance(action, ValidatedAction):
            return ActionResult(False, "unknown", error="Action must be validated before dispatch.")

        if action.action == "open_file":
            return open_file(action.target)
        if action.action == "open_folder":
            return open_folder(action.target)
        if action.action == "open_url":
            return open_url(action.target)
        if action.action == "launch_application":
            return launch_application(action.target, self.apps)

        # Defensive guard; validate_action already rejects this.
        return ActionResult(False, action.action, error="Unknown action.")
