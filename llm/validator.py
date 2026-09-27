"""Strict validation of untrusted LLM output."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from .result import LLMCommandResult, LLMResponseValidationError, LLMStatus

_ALLOWED_ACTIONS = {"open_file", "open_folder", "open_url", "launch_application"}
_ALLOWED_STATUSES = {"action", "needs_clarification", "unsupported", "invalid", "memory"}
_MEMORY_SECRET_WORDS = ("password", "api_key", "token", "secret", "credential", "private_key")
_MEMORY_PREFERENCE_KEYS = {"response_style", "preferred_language", "confirmation_mode"}
_FOLDER_ALIASES = {
    "downloads": "Downloads", "documents": "Documents", "desktop": "Desktop",
    "pictures": "Pictures", "music": "Music", "videos": "Videos",
}


def _error(message: str) -> LLMResponseValidationError:
    return LLMResponseValidationError(message)


def _strict_object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise _error(f"{label} must be an object.")
    return value


def _message(data: Mapping[str, Any]) -> str:
    value = data.get("message")
    if not isinstance(value, str) or not value.strip():
        raise _error("'message' must be a non-empty string.")
    value = value.strip()
    if len(value) > 2000 or "\x00" in value:
        raise _error("'message' is too long or contains invalid characters.")
    return value


def _normalize_folder_target(target: str) -> str:
    alias = _FOLDER_ALIASES.get(target.casefold())
    return str(Path.home() / alias) if alias else target



def _path_allowed_for_untrusted_output(target: str, roots: tuple[str, ...] | list[str] | None) -> bool:
    if roots is None:
        return True
    try:
        candidate = Path(target).expanduser().resolve(strict=False)
        for root in roots:
            base = Path(root).expanduser().resolve(strict=False)
            if candidate == base or base in candidate.parents:
                return True
    except (OSError, RuntimeError, ValueError):
        return False
    return False

def validate_llm_response(raw: str | Mapping[str, Any], *, approved_apps: Mapping[str, Any], allowed_path_roots: tuple[str, ...] | list[str] | None = None) -> LLMCommandResult:
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError as exc:
        raise _error("LLM returned malformed JSON.") from exc

    data = _strict_object(data, "LLM response")
    if set(data) - {"status", "action", "message", "memory"}:
        raise _error("LLM response contains unexpected fields.")
    status = data.get("status")
    if status not in _ALLOWED_STATUSES:
        raise _error("LLM response contains an unsupported status.")
    message = _message(data)

    if status == "memory":
        if "action" in data:
            raise _error("Memory responses must not contain an action object.")
        memory = _strict_object(data.get("memory"), "'memory'")
        if set(memory) != {"operation", "category", "key", "value"}:
            raise _error("Memory operation contains unexpected or missing fields.")
        operation = memory.get("operation")
        category = memory.get("category")
        key = memory.get("key")
        value = memory.get("value")
        if operation not in {"save", "retrieve", "update", "delete", "clear"}:
            raise _error("Unsupported memory operation.")
        if category not in {"preferred_application", "preferred_folder", "assistant_preference"}:
            raise _error("Unsupported memory category.")
        if not isinstance(key, str) or not key.strip() or len(key) > 100:
            raise _error("Memory key is invalid.")
        if any(word in key.casefold() for word in _MEMORY_SECRET_WORDS):
            raise _error("Memory keys may not contain secrets or credentials.")
        if category == "assistant_preference" and key not in _MEMORY_PREFERENCE_KEYS:
            raise _error("Unsupported assistant preference key.")
        if operation == "clear":
            if key != "default" or value not in (None, ""):
                raise _error("Clear memory operation has invalid parameters.")
        else:
            if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 500):
                raise _error("Memory value is invalid.")
            if isinstance(value, str) and any(word in value.casefold() for word in _MEMORY_SECRET_WORDS):
                raise _error("Memory values may not contain secrets or credentials.")
            if operation in {"save", "update"} and value is None:
                raise _error("Memory save/update requires a value.")
        return LLMCommandResult(LLMStatus.MEMORY, message, memory={
            "operation": operation, "category": category, "key": key.strip(), "value": (value.strip() if isinstance(value, str) else "")
        })

    if "memory" in data:
        raise _error("Non-memory responses must not contain a memory object.")
    if "action" in data and status != "action":
        raise _error("Non-action responses must not contain an action object.")
    if status != "action":
        return LLMCommandResult(LLMStatus(status), message)

    action = _strict_object(data.get("action"), "'action'")
    if set(action) != {"action", "target"}:
        raise _error("Action must contain only 'action' and 'target'.")
    name = action.get("action")
    target = action.get("target")
    if name not in _ALLOWED_ACTIONS:
        raise _error("LLM returned an unsupported action.")
    if not isinstance(target, str) or not target.strip() or "\x00" in target:
        raise _error("Action target must be a non-empty string without null characters.")
    target = target.strip()
    if len(target) > 4096:
        raise _error("LLM action target is too long.")

    if name == "open_url":
        try:
            parsed = urlparse(target)
        except ValueError as exc:
            raise _error("LLM returned an invalid or unsupported URL.") from exc
        if (parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc
                or parsed.username is not None or parsed.password is not None
                or any(ord(ch) < 32 or ord(ch) == 127 for ch in target)
                or any(ch.isspace() for ch in target)):
            raise _error("LLM returned an invalid or unsupported URL.")
    elif name == "launch_application":
        # Application targets are names only, never executable paths.
        if any(token in target for token in ("\\", "/", ":")):
            raise _error("LLM may only return an approved application name.")
        if target.casefold() not in {str(k).casefold() for k in approved_apps}:
            raise _error("LLM requested an application that is not approved/configured.")
    elif name == "open_folder":
        target = _normalize_folder_target(target)
        path = Path(target)
        if not path.is_dir():
            raise _error("LLM returned a folder target that cannot be safely resolved.")
        if not _path_allowed_for_untrusted_output(target, allowed_path_roots):
            raise _error("LLM returned a folder outside the configured safe search locations.")
    elif name == "open_file":
        path = Path(target)
        if not path.is_file():
            raise _error("LLM returned a file target that cannot be safely resolved.")
        if not _path_allowed_for_untrusted_output(target, allowed_path_roots):
            raise _error("LLM returned a file outside the configured safe search locations.")

    return LLMCommandResult(LLMStatus.ACTION, message, {"action": name, "target": target})
