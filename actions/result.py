"""Typed, predictable results returned by every Stage 2 action."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.errors import ErrorInfo


@dataclass(frozen=True)
class ActionResult:
    success: bool
    action: str
    message: str | None = None
    error: str | None = None
    error_info: ErrorInfo | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "action": self.action,
            "message": self.message,
            "error": self.error,
        }
