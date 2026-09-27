"""Stage 6 response text -> TTS provider -> default audio output."""
from __future__ import annotations

import logging

from core.errors import ErrorCategory, error_info
from dataclasses import dataclass
from threading import Event, Lock

from .audio import AudioOutput
from .provider import TTSProvider
from .result import TTSResult, TTSStatus, TTSError
from .text import sanitize_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AssistantResponse:
    text: str
    tts: TTSResult


class TTSPipeline:
    """Optional output layer. It never receives or executes actions."""

    def __init__(self, provider: TTSProvider | None, audio_output: AudioOutput | None,
                 *, enabled: bool = True, max_chars: int = 2000):
        self.provider = provider
        self.audio_output = audio_output
        self.enabled = bool(enabled)
        self.max_chars = max_chars
        self._playback_lock = Lock()
        self._closed = Event()

    def close(self) -> None:
        """Stop local audio resources and prevent new speech during shutdown."""
        if self._closed.is_set():
            return
        self._closed.set()
        for resource in (self.audio_output, self.provider):
            close = getattr(resource, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    logger.debug("TTS resource cleanup failed.", exc_info=False)

    def speak(self, text: str) -> TTSResult:
        if self._closed.is_set():
            return TTSResult(TTSStatus.ERROR, "Text-to-Speech is shutting down.")
        if not self.enabled:
            return TTSResult(TTSStatus.DISABLED, "Text-to-Speech is disabled.")
        try:
            safe_text = sanitize_text(text, max_chars=self.max_chars)
        except TTSError as exc:
            info = error_info(exc, category=ErrorCategory.VALIDATION, user_message=str(exc))
            logger.warning("TTS text rejected: %s", info.diagnostic)
            return TTSResult(TTSStatus.ERROR, info.user_message, error_info=info)

        if self.provider is None:
            return TTSResult(TTSStatus.ERROR, "Text-to-Speech provider is not configured.")
        if self.audio_output is None:
            return TTSResult(TTSStatus.ERROR, "Audio output is unavailable.")

        try:
            # Synchronous, serialized playback gives a deterministic no-overlap policy.
            with self._playback_lock:
                audio = self.provider.synthesize(safe_text)
                self.audio_output.play(audio)
        except TTSError as exc:
            info = error_info(exc, category=ErrorCategory.AUDIO, user_message="Text-to-Speech failed.")
            logger.warning("TTS failed: %s", info.diagnostic)
            return TTSResult(TTSStatus.ERROR, info.user_message, error_info=info)
        except Exception as exc:
            info = error_info(exc, category=ErrorCategory.INTERNAL, user_message="Text-to-Speech failed.")
            logger.error("Unexpected TTS failure (%s).", type(exc).__name__)
            return TTSResult(TTSStatus.ERROR, info.user_message, error_info=info)
        return TTSResult(TTSStatus.SUCCESS, "Speech played successfully.")


def build_pipeline(config: dict) -> TTSPipeline:
    from .audio import WindowsDefaultAudioOutput
    from .provider import build_provider

    enabled = bool(config.get("enabled", True))
    provider = build_provider(config) if enabled else None
    audio_output = WindowsDefaultAudioOutput() if enabled and provider is not None else None
    return TTSPipeline(
        provider,
        audio_output,
        enabled=enabled,
        max_chars=int(config.get("max_chars", 2000)),
    )
