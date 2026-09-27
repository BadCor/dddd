"""Speech-to-text provider abstraction and OpenAI transcription provider."""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from urllib.parse import urlparse
from dataclasses import dataclass
from typing import Protocol

from .result import (
    SpeechConfigurationError,
    SpeechRecognitionError,
    SpeechRecognitionTimeoutError,
)

logger = logging.getLogger(__name__)


def _validate_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme.lower() not in {"https", "http"} or not parsed.netloc:
        raise SpeechConfigurationError("Speech endpoint must be a valid HTTP(S) URL.")
    if parsed.username is not None or parsed.password is not None:
        raise SpeechConfigurationError("Speech endpoint may not contain embedded credentials.")
    if parsed.scheme.lower() == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise SpeechConfigurationError("Non-local speech endpoints must use HTTPS.")
    return endpoint


class SpeechRecognitionProvider(Protocol):
    def transcribe(self, audio: bytes, *, filename: str = "speech.wav") -> str:
        """Return plain recognized text for a complete audio recording."""


@dataclass(frozen=True)
class OpenAITranscriptionProvider:
    """HTTP client for OpenAI's file transcription endpoint.

    Audio is sent only when ``transcribe`` is called. No audio is written to disk.
    """

    model: str
    endpoint: str
    api_key_env_var: str
    timeout: float = 30.0
    max_response_size: int = 65536
    language: str | None = "ru"

    def transcribe(self, audio: bytes, *, filename: str = "speech.wav") -> str:
        api_key = os.getenv(self.api_key_env_var)
        if not api_key:
            raise SpeechConfigurationError("Speech recognition API key is not configured.")
        if not audio:
            raise SpeechRecognitionError("Audio data is empty.")

        boundary = "----VoiceAssistantBoundary7d9f"
        body = self._multipart_body(boundary, audio, filename)
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read(self.max_response_size + 1)
        except TimeoutError as exc:
            raise SpeechRecognitionTimeoutError("Speech recognition request timed out.") from exc
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise SpeechRecognitionError("Speech recognition authentication failed.") from exc
            if exc.code == 429:
                raise SpeechRecognitionError("Speech recognition provider rate limit reached.") from exc
            raise SpeechRecognitionError("Speech recognition provider request failed.") from exc
        except urllib.error.URLError as exc:
            raise SpeechRecognitionError("Speech recognition provider is unavailable.") from exc
        except OSError as exc:
            raise SpeechRecognitionError("Speech recognition request failed.") from exc

        if len(raw) > self.max_response_size:
            raise SpeechRecognitionError("Speech recognition response exceeded the configured size limit.")
        try:
            data = json.loads(raw.decode("utf-8"))
            text = data["text"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise SpeechRecognitionError("Speech recognition provider returned an invalid response.") from exc
        if not isinstance(text, str):
            raise SpeechRecognitionError("Speech recognition provider returned invalid text.")
        return text.strip()

    def _multipart_body(self, boundary: str, audio: bytes, filename: str) -> bytes:
        safe_filename = filename.replace('"', "_").replace("\\", "_").replace("/", "_")
        chunks = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n{self.model}\r\n".encode(),
        ]
        if self.language:
            chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"language\"\r\n\r\n{self.language}\r\n".encode())
        chunks.extend([
            (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{safe_filename}\"\r\n"
                "Content-Type: audio/wav\r\n\r\n"
            ).encode(),
            audio,
            f"\r\n--{boundary}--\r\n".encode(),
        ])
        return b"".join(chunks)


def build_provider(config: dict) -> SpeechRecognitionProvider | None:
    provider = str(config.get("provider", "none")).strip().lower()
    if provider in {"none", ""}:
        return None
    if provider in {"openai", "openai_transcription"}:
        endpoint = _validate_endpoint(str(config.get("endpoint", "https://api.openai.com/v1/audio/transcriptions")))
        timeout = float(config.get("recognition_timeout", 30))
        max_response_size = int(config.get("max_response_size", 65536))
        if not 0.1 <= timeout <= 120:
            raise SpeechConfigurationError("Speech recognition timeout is outside the safe range.")
        if not 256 <= max_response_size <= 1_048_576:
            raise SpeechConfigurationError("Speech response size limit is outside the safe range.")
        return OpenAITranscriptionProvider(
            model=str(config.get("model", "gpt-transcribe")),
            endpoint=endpoint,
            api_key_env_var=str(config.get("api_key_env_var", "ASSISTANT_SPEECH_API_KEY")),
            timeout=timeout,
            max_response_size=max_response_size,
            language=str(config.get("language", "ru")).strip() or None,
        )
    raise SpeechConfigurationError(f"Unsupported speech provider: '{provider}'.")
