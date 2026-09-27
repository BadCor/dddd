"""Typed models for the small, explicit Stage 9 persistence layer."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from core.errors import ErrorInfo


class MemoryCategory(str, Enum):
    PREFERRED_APPLICATION = "preferred_application"
    PREFERRED_FOLDER = "preferred_folder"
    ASSISTANT_PREFERENCE = "assistant_preference"


class MemoryOperationType(str, Enum):
    SAVE = "save"
    RETRIEVE = "retrieve"
    UPDATE = "update"
    DELETE = "delete"
    CLEAR = "clear"


@dataclass(frozen=True)
class MemoryOperation:
    operation: MemoryOperationType
    category: MemoryCategory | None = None
    key: str | None = None
    value: str | None = None


@dataclass(frozen=True)
class MemoryResult:
    success: bool
    message: str
    value: str | None = None
    error_info: ErrorInfo | None = None


@dataclass(frozen=True)
class UserSettings:
    tts_enabled: bool | None = None
    tts_voice: str | None = None
    tts_rate: int | None = None
    tts_volume: float | None = None
    microphone_index: int | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
