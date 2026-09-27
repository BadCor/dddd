"""Structured Stage 6 text-to-speech results and errors."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.errors import ErrorInfo


class TTSStatus(str, Enum):
    SUCCESS = "success"
    DISABLED = "disabled"
    ERROR = "error"


@dataclass(frozen=True)
class TTSResult:
    status: TTSStatus
    message: str = ""
    error_info: ErrorInfo | None = None


class TTSError(Exception):
    """Base class for expected TTS-layer failures."""


class TTSConfigurationError(TTSError):
    pass


class TTSTextError(TTSError):
    pass


class TTSSynthesisError(TTSError):
    pass


class TTSTimeoutError(TTSSynthesisError):
    pass


class TTSPlaybackError(TTSError):
    pass
