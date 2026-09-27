"""Explicit, allowlisted memory operations. No conversation archive is kept."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from core.errors import ErrorCategory, error_info

from .models import MemoryCategory, MemoryOperation, MemoryOperationType, MemoryResult
from .storage import JsonStorage, StorageError

_ALLOWED_PREFERENCES = {"response_style", "preferred_language", "confirmation_mode"}
_SECRET_WORDS = ("password", "api_key", "token", "secret", "credential", "private_key")
_MAX_VALUE = 500


def _safe_text(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Memory values must be text.")
    value = value.strip()
    if not value or len(value) > _MAX_VALUE or "\x00" in value:
        raise ValueError("Memory value is invalid.")
    return value


def _reject_secret(key: str, value: str | None = None) -> None:
    haystack = key.casefold() + " " + (value or "").casefold()
    if any(word in haystack for word in _SECRET_WORDS):
        raise ValueError("Secrets and credentials cannot be stored in memory.")


class MemoryManager:
    """Stores only three supported categories and only after explicit operations."""

    def __init__(self, storage: JsonStorage, approved_apps: Mapping[str, Any] | None = None,
                 allowed_folder_roots: tuple[str, ...] | list[str] | None = None):
        self.storage = storage
        self.approved_apps = {str(k).casefold() for k in (approved_apps or {})}
        self.allowed_folder_roots = tuple(Path(root).expanduser() for root in (allowed_folder_roots or ()))
        self._memory = self._load_safe()

    def _load_safe(self) -> dict[str, dict[str, str]]:
        try:
            data = self.storage.load()
        except StorageError:
            data = {"version": 1, "settings": {}, "memory": {}}
            try:
                self.storage.save(data)
            except StorageError:
                pass
        raw = data.get("memory", {})
        if not isinstance(raw, dict):
            return {category.value: {} for category in MemoryCategory}
        safe: dict[str, dict[str, str]] = {category.value: {} for category in MemoryCategory}
        for category in MemoryCategory:
            entries = raw.get(category.value, {})
            if not isinstance(entries, dict):
                continue
            for key, value in entries.items():
                try:
                    self._validate_entry(category, str(key), value)
                    safe[category.value][str(key)] = str(value).strip()
                except ValueError:
                    continue
        return safe

    def _validate_entry(self, category: MemoryCategory, key: str, value: Any) -> str:
        if category is MemoryCategory.ASSISTANT_PREFERENCE and key not in _ALLOWED_PREFERENCES:
            raise ValueError("Unsupported assistant preference.")
        if key != "default" and category is not MemoryCategory.ASSISTANT_PREFERENCE:
            raise ValueError("Unsupported memory key.")
        safe = _safe_text(value)
        _reject_secret(key, safe)
        if category is MemoryCategory.PREFERRED_APPLICATION:
            if safe.casefold() not in self.approved_apps:
                raise ValueError("Application is not in the approved application list.")
        if category is MemoryCategory.PREFERRED_FOLDER:
            path = Path(safe)
            if not path.is_absolute():
                raise ValueError("Preferred folder must be an absolute path.")
            if self.allowed_folder_roots:
                try:
                    resolved = path.resolve(strict=False)
                    allowed = any(resolved == root.resolve(strict=False) or root.resolve(strict=False) in resolved.parents
                                  for root in self.allowed_folder_roots)
                except (OSError, RuntimeError, ValueError):
                    allowed = False
                if not allowed:
                    raise ValueError("Preferred folder is outside the configured safe locations.")
        return safe

    def apply(self, operation: MemoryOperation) -> MemoryResult:
        try:
            op = MemoryOperationType(operation.operation)
            category = MemoryCategory(operation.category) if operation.category is not None else None
            if op is MemoryOperationType.CLEAR:
                self.clear()
                return MemoryResult(True, "Supported memory cleared.")
            if category is None or operation.key is None:
                raise ValueError("Memory category and key are required.")
            key = operation.key.strip()
            if op in {MemoryOperationType.SAVE, MemoryOperationType.UPDATE}:
                value = self._validate_entry(category, key, operation.value)
                if op is MemoryOperationType.SAVE and key in self._memory[category.value]:
                    return MemoryResult(False, "That memory item already exists; use update instead.")
                self._memory[category.value][key] = value
                self._persist()
                return MemoryResult(True, "Memory saved.", value)
            if op is MemoryOperationType.RETRIEVE:
                value = self._memory.get(category.value, {}).get(key)
                return MemoryResult(value is not None, "Memory found." if value is not None else "Memory item not found.", value)
            if op is MemoryOperationType.DELETE:
                if key not in self._memory.get(category.value, {}):
                    return MemoryResult(False, "Memory item not found.")
                del self._memory[category.value][key]
                self._persist()
                return MemoryResult(True, "Memory item deleted.")
            raise ValueError("Unsupported memory operation.")
        except (ValueError, StorageError) as exc:
            info = error_info(exc, category=ErrorCategory.STORAGE if isinstance(exc, StorageError) else ErrorCategory.SECURITY, user_message=str(exc))
            return MemoryResult(False, info.user_message, error_info=info)
        except Exception as exc:
            info = error_info(exc, category=ErrorCategory.INTERNAL, user_message="Memory operation failed safely.")
            return MemoryResult(False, info.user_message, error_info=info)

    def get(self, category: MemoryCategory, key: str = "default") -> MemoryResult:
        return self.apply(MemoryOperation(MemoryOperationType.RETRIEVE, category, key))

    def clear(self) -> None:
        self._memory = {category.value: {} for category in MemoryCategory}
        self._persist()

    def clear_supported(self) -> MemoryResult:
        self.clear()
        return MemoryResult(True, "Supported memory cleared.")

    def validate_for_use(self, category: MemoryCategory, key: str = "default") -> MemoryResult:
        result = self.get(category, key)
        if not result.success or result.value is None:
            return result
        if category is MemoryCategory.PREFERRED_APPLICATION:
            if result.value.casefold() not in self.approved_apps:
                return MemoryResult(False, "Stored application is no longer approved.")
        elif category is MemoryCategory.PREFERRED_FOLDER:
            path = Path(result.value)
            if not path.is_dir():
                return MemoryResult(False, "Stored folder no longer exists or is not a folder.")
        return result

    def _persist(self) -> None:
        data = self.storage.load()
        data["version"] = 1
        data.setdefault("settings", {})
        data["memory"] = {key: dict(value) for key, value in self._memory.items()}
        self.storage.save(data)


def parse_explicit_memory_request(text: str, approved_apps: Mapping[str, Any] | None = None) -> MemoryOperation | None:
    """Small deterministic recognizer for explicit memory phrases only."""
    raw = " ".join(str(text).strip().split())
    if not raw:
        return None
    apps = {str(k).casefold(): str(k) for k in (approved_apps or {})}
    if re.match(r"^(?:clear|clear memory|forget all|очисти память|забудь всё)$", raw, re.IGNORECASE):
        return MemoryOperation(MemoryOperationType.CLEAR, MemoryCategory.ASSISTANT_PREFERENCE, "default", None)
    retrieve = re.match(r"^(?:what do you remember about|show my memory|покажи память|что ты помнишь)\s*(.*)$", raw, re.IGNORECASE)
    if retrieve:
        return MemoryOperation(MemoryOperationType.RETRIEVE, MemoryCategory.ASSISTANT_PREFERENCE, "response_style", None)
    patterns = [
        (r"^(?:remember|save|запомни|сохрани)\s+(?:that\s+)?(?:i\s+)?(?:use|использую)\s+(.+)$", MemoryCategory.PREFERRED_APPLICATION),
        (r"^(?:remember|запомни)\s+(?:that\s+)?(?:my\s+)?(?:project\s+)?folder\s+(?:is|=|—|-)\s*(.+)$", MemoryCategory.PREFERRED_FOLDER),
        (r"^(?:запомни|сохрани)\s+(?:что\s+)?(?:моя\s+)?папка(?:\s+проекта)?\s*(?:это|=|—|-)\s*(.+)$", MemoryCategory.PREFERRED_FOLDER),
    ]
    for pattern, category in patterns:
        match = re.match(pattern, raw, re.IGNORECASE)
        if not match:
            continue
        value = match.group(1).strip().strip('"\'')
        if category is MemoryCategory.PREFERRED_APPLICATION:
            canonical = apps.get(value.casefold())
            if canonical is None:
                return MemoryOperation(MemoryOperationType.SAVE, category, "default", value)
            value = canonical
        return MemoryOperation(MemoryOperationType.SAVE, category, "default", value)
    return None
