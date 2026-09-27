"""Audio playback abstraction for Stage 6."""
from __future__ import annotations

from typing import Protocol
import logging
import threading

from .result import TTSPlaybackError


class AudioOutput(Protocol):
    def play(self, audio: bytes) -> None:
        """Play a complete audio payload synchronously."""

    def close(self) -> None:
        """Stop playback and release output resources."""


class WindowsDefaultAudioOutput:
    """Synchronous playback through the Windows default audio device."""

    def __init__(self) -> None:
        self._closed = threading.Event()

    def close(self) -> None:
        self._closed.set()
        try:
            import winsound
            winsound.PlaySound(None, winsound.SND_PURGE)
        except (ImportError, RuntimeError, OSError):
            logging.getLogger(__name__).debug("Audio output cleanup was unavailable.", exc_info=False)

    def play(self, audio: bytes) -> None:
        if self._closed.is_set():
            raise TTSPlaybackError("Audio output is closed.")
        if not audio:
            raise TTSPlaybackError("Audio data is empty.")
        try:
            import winsound
        except ImportError as exc:
            raise TTSPlaybackError("Windows audio playback is unavailable.") from exc
        try:
            # SND_SYNC prevents overlapping speech: the next response waits
            # until this playback finishes. SND_MEMORY avoids persistent files.
            winsound.PlaySound(audio, winsound.SND_MEMORY | winsound.SND_SYNC)
        except (RuntimeError, OSError) as exc:
            raise TTSPlaybackError("Audio playback failed.") from exc
