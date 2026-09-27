"""Validation for all supported Stage 2 actions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from typing import Any, Mapping

from core.exceptions import ActionValidationError

SUPPORTED_ACTIONS = frozenset({"open_file", "open_folder", "open_url", "launch_application"})


@dataclass(frozen=True)
class ValidatedAction:
    action: str
    target: str


def _require_mapping(raw: Any) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise ActionValidationError("Action must be a mapping/object.")
    return raw


def _validate_action_name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ActionValidationError("Action name must be a non-empty string.")
    action = value.strip()
    if action not in SUPPORTED_ACTIONS:
        raise ActionValidationError(f"Unknown action: '{action}'.")
    return action


def _require_target(raw: Mapping[str, Any]) -> str:
    if "target" not in raw:
        raise ActionValidationError("Missing required parameter: 'target'.")
    target = raw["target"]
    if not isinstance(target, str) or not target.strip():
        raise ActionValidationError("Parameter 'target' must be a non-empty string.")
    if "\x00" in target:
        raise ActionValidationError("Parameter 'target' contains an invalid null character.")
    return target.strip()


def _validate_path(target: str, label: str) -> None:
    try:
        path = Path(target)
        # Construction alone is intentionally enough here; existence/type checks
        # belong to the concrete action handlers so validation remains deterministic.
        if str(path) != target and not target.strip():
            raise ValueError
    except (TypeError, ValueError, OSError) as exc:
        raise ActionValidationError(f"Invalid {label} path.") from exc


def _validate_url(target: str) -> None:
    try:
        parsed = urlparse(target)
    except ValueError as exc:
        raise ActionValidationError("Invalid URL.") from exc

    if parsed.scheme.lower() not in {"http", "https"}:
        raise ActionValidationError("Only http:// and https:// URLs are allowed.")
    if not parsed.netloc:
        raise ActionValidationError("URL must contain a host.")
    if parsed.username is not None or parsed.password is not None:
        raise ActionValidationError("URLs containing embedded credentials are not allowed.")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in target) or any(ch.isspace() for ch in target):
        raise ActionValidationError("URL must not contain whitespace or control characters.")


def validate_action(raw: Any) -> ValidatedAction:
    """Validate and normalize a raw action request without executing it."""
    data = _require_mapping(raw)
    action = _validate_action_name(data.get("action"))
    target = _require_target(data)

    # Reject unexpected parameters too: this keeps the action schema explicit.
    allowed_keys = {"action", "target"}
    unexpected = set(data) - allowed_keys
    if unexpected:
        names = ", ".join(sorted(map(str, unexpected)))
        raise ActionValidationError(f"Unsupported action parameters: {names}.")

    if action in {"open_file", "open_folder"}:
        _validate_path(target, action)
    elif action == "open_url":
        _validate_url(target)
    # launch_application only validates the name here. Resolution against the
    # configured allowlist happens in the application handler.

    return ValidatedAction(action=action, target=target)
