"""Typed results and errors for Stage 4 LLM integration."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from core.errors import ErrorInfo


class LLMStatus(str, Enum):
    ACTION = "action"
    NEEDS_CLARIFICATION = "needs_clarification"
    UNSUPPORTED = "unsupported"
    INVALID = "invalid"
    ERROR = "error"
    MEMORY = "memory"


@dataclass(frozen=True)
class LLMCommandResult:
    status: LLMStatus
    message: str
    action: dict[str, str] | None = None
    memory: dict[str, str] | None = None
    error_info: ErrorInfo | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"status": self.status.value, "message": self.message}
        if self.action is not None:
            data["action"] = dict(self.action)
        if self.memory is not None:
            data["memory"] = dict(self.memory)
        return data


class LLMError(Exception):
    """Base class for expected provider/LLM failures."""


class LLMConfigurationError(LLMError):
    pass


class LLMProviderError(LLMError):
    pass


class LLMTimeoutError(LLMProviderError):
    pass


class LLMResponseValidationError(LLMError):
    pass
