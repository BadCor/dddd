"""Runtime paths for source and PyInstaller deployments."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "Voice Assistant"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundled_root() -> Path:
    """Return the read-only application resource root."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def executable_root() -> Path:
    """Return the directory containing the packaged executable, or source root."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def user_data_root(app_name: str = APP_DIR_NAME) -> Path:
    """Return writable per-user data root on Windows."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    safe_name = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in app_name).strip() or APP_DIR_NAME
    return base / safe_name
