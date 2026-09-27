"""Structured, privacy-conscious internal error information for Stage 10."""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ErrorCategory(str, Enum):
    CONFIGURATION = "configuration"
    VALIDATION = "validation"
    SECURITY = "security"
    NETWORK = "network"
    AUDIO = "audio"
    DISCOVERY = "discovery"
    STORAGE = "storage"
    ACTION = "action"
    GUI = "gui"
    INTERNAL = "internal"


@dataclass(frozen=True)
class ErrorInfo:
    """Safe internal error record; user-facing text is deliberately separate."""
    category: ErrorCategory
    user_message: str
    diagnostic: str = ""
    recoverable: bool = True


def redact_secrets(value: Any) -> str:
    """Return diagnostic text with common credentials and secret values redacted."""
    text = str(value)
    patterns = (
        (r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+", r"\1[REDACTED]"),
        (r"(?i)(bearer\s+)[^\s,;]+", r"\1[REDACTED]"),
        (r"(?i)((?:api[_-]?key|password|passwd|token|secret|credential|private[_-]?key)\s*[:=]\s*)[^\s,;]+", r"\1[REDACTED]"),
        (r"(?i)(ASSISTANT_(?:LLM|SPEECH)_API_KEY\s*[:=]\s*)[^\s,;]+", r"\1[REDACTED]"),
    )
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text)
    return text[:4000]


def error_info(exc: BaseException, *, category: ErrorCategory,
               user_message: str, recoverable: bool = True) -> ErrorInfo:
    """Build a safe structured error without exposing exception details to users."""
    return ErrorInfo(category, user_message, redact_secrets(exc), recoverable)
