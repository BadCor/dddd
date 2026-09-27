"""Structured speech recognition results and errors."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.errors import ErrorInfo


class SpeechStatus(str, Enum):
    SUCCESS = "success"
    NO_SPEECH = "no_speech"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class SpeechResult:
    status: SpeechStatus
    text: str = ""
    message: str = ""
    error_info: ErrorInfo | None = None


class SpeechError(Exception):
    """Base class for expected speech-layer failures."""


class SpeechConfigurationError(SpeechError):
    pass


class MicrophoneError(SpeechError):
    pass


class MicrophoneUnavailableError(MicrophoneError):
    pass


class MicrophoneAccessError(MicrophoneError):
    pass


class MicrophoneDisconnectedError(MicrophoneError):
    pass


class AudioCaptureError(MicrophoneError):
    pass


class RecordingTimeoutError(MicrophoneError):
    pass


class SilenceTimeoutError(MicrophoneError):
    pass


class SpeechRecognitionError(SpeechError):
    pass


class SpeechRecognitionTimeoutError(SpeechRecognitionError):
    pass
