"""Small atomic JSON storage for non-secret user settings and memory."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from core.runtime_paths import user_data_root


class StorageError(Exception):
    """Expected local persistence failure."""


class JsonStorage:
    """Read/write one versioned JSON document with atomic replacement."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "settings": {}, "memory": {}}
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise StorageError("Stored user data could not be read safely.") from exc
        if not isinstance(data, dict):
            raise StorageError("Stored user data has an invalid format.")
        return data

    def save(self, data: dict[str, Any]) -> None:
        if not isinstance(data, dict):
            raise StorageError("Stored user data must be an object.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".user-data-", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        except OSError as exc:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise StorageError("User data could not be saved safely.") from exc


def default_storage_path(app_name: str = "Voice Assistant") -> Path:
    """Use the per-user Windows local application-data directory."""
    base = user_data_root()
    safe_name = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in app_name).strip() or "Voice Assistant"
    return base / safe_name / "user_data.json"
