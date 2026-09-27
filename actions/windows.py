"""Small OS/browser integration points. These functions are deliberately mockable."""

from __future__ import annotations

import os
import webbrowser
from pathlib import Path


def open_path(path: Path) -> None:
    """Open a file or folder using the native Windows association."""
    if os.name != "nt":
        raise OSError("Windows path opening is only supported on Windows.")
    os.startfile(str(path))  # type: ignore[attr-defined]


def open_browser_url(url: str) -> None:
    """Open an HTTP(S) URL with the user's default browser."""
    if not webbrowser.open(url, new=2):
        raise OSError("The default browser rejected the URL.")


# Alias used by the application launcher; it still resolves through the same
# isolated OS boundary and never invokes a shell.
launch_configured_application = open_path
