"""Replaceable text-to-speech providers for Stage 6."""
from __future__ import annotations

import logging
import tempfile
import threading
from pathlib import Path
from typing import Protocol

from .result import TTSConfigurationError, TTSSynthesisError, TTSTimeoutError

logger = logging.getLogger(__name__)


class TTSProvider(Protocol):
    def synthesize(self, text: str) -> bytes:
        """Return a complete WAV payload without playing it."""


class WindowsSAPIProvider:
    """Local Windows SAPI provider through pyttsx3."""

    def __init__(self, *, voice: str | None = None, rate: int = 180, volume: float = 1.0,
                 timeout: float = 30.0):
        self.voice = voice.strip() if isinstance(voice, str) and voice.strip() else None
        self.rate = max(50, min(int(rate), 400))
        self.volume = max(0.0, min(float(volume), 1.0))
        self.timeout = max(1.0, min(float(timeout), 120.0))
        self._closed = threading.Event()
        self._engine_lock = threading.Lock()
        self._active_engine = None

    def close(self) -> None:
        """Stop an active local SAPI engine when the application shuts down."""
        self._closed.set()
        with self._engine_lock:
            engine = self._active_engine
        if engine is not None:
            try:
                engine.stop()
            except Exception:
                logger.debug("TTS engine stop failed during provider cleanup.", exc_info=False)

    def synthesize(self, text: str) -> bytes:
        if self._closed.is_set():
            raise TTSConfigurationError("Text-to-Speech provider is closed.")
        if not text.strip():
            raise TTSSynthesisError("Text-to-Speech input is empty.")

        result: dict[str, bytes | Exception] = {}
        done = threading.Event()

        def worker() -> None:
            temp_path: Path | None = None
            try:
                import pyttsx3
            except ImportError:
                result["error"] = TTSConfigurationError("The local Windows TTS provider is not installed.")
                done.set()
                return
            try:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp:
                    temp_path = Path(temp.name)
                engine = pyttsx3.init()
                with self._engine_lock:
                    self._active_engine = engine
                if self._closed.is_set():
                    engine.stop()
                    raise TTSConfigurationError("Text-to-Speech provider is closed.")
                engine.setProperty("rate", self.rate)
                engine.setProperty("volume", self.volume)
                if self.voice:
                    engine.setProperty("voice", self.voice)
                engine.save_to_file(text, str(temp_path))
                engine.runAndWait()
                try:
                    engine.stop()
                except Exception:
                    logger.debug("TTS engine stop failed during cleanup.", exc_info=False)

                if self._closed.is_set():
                    raise TTSConfigurationError("Text-to-Speech provider is closed.")
                if not temp_path.exists():
                    raise TTSSynthesisError("Text-to-Speech produced no audio.")
                audio = temp_path.read_bytes()
                if not audio or not audio.startswith(b"RIFF") or b"WAVE" not in audio[:32]:
                    raise TTSSynthesisError("Text-to-Speech produced invalid audio.")
                result["audio"] = audio
            except Exception as exc:
                # The concrete provider exception is deliberately retained only
                # inside this worker; the caller receives a sanitized error.
                result["error"] = exc
            finally:
                with self._engine_lock:
                    self._active_engine = None
                if temp_path is not None:
                    try:
                        temp_path.unlink(missing_ok=True)
                    except OSError:
                        logger.warning("Could not remove temporary TTS audio file.")
                done.set()

        thread = threading.Thread(target=worker, name="tts-synthesis", daemon=True)
        thread.start()
        if not done.wait(self.timeout):
            raise TTSTimeoutError("Text-to-Speech synthesis timed out.")

        error = result.get("error")
        if error is not None:
            if isinstance(error, TTSConfigurationError):
                raise error
            raise TTSSynthesisError("Text-to-Speech synthesis failed.") from error
        audio = result.get("audio")
        if not isinstance(audio, bytes):
            raise TTSSynthesisError("Text-to-Speech produced no audio.")
        return audio


def build_provider(config: dict) -> TTSProvider | None:
    provider = str(config.get("provider", "none")).strip().lower()
    if provider in {"none", ""}:
        return None
    if provider in {"windows_sapi", "sapi", "pyttsx3", "local"}:
        return WindowsSAPIProvider(
            voice=config.get("voice"),
            rate=int(config.get("rate", 180)),
            volume=float(config.get("volume", 1.0)),
            timeout=float(config.get("timeout", 30)),
        )
    raise TTSConfigurationError(f"Unsupported TTS provider: '{provider}'.")
