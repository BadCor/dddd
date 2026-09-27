"""Typed results produced by the Stage 3 text command parser."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class CommandStatus(str, Enum):
    ACTION = "action"
    NEEDS_CLARIFICATION = "needs_clarification"
    UNSUPPORTED = "unsupported"
    INVALID = "invalid"


@dataclass(frozen=True)
class CommandResult:
    status: CommandStatus
    message: str
    action: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status.value,
            "message": self.message,
        }
        if self.action is not None:
            result["action"] = dict(self.action)
        return result
