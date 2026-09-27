"""Microphone discovery and bounded, silence-aware recording."""
from __future__ import annotations

import logging
import math
import time
import wave
import threading
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Protocol

from .result import (
    AudioCaptureError,
    MicrophoneAccessError,
    MicrophoneDisconnectedError,
    MicrophoneUnavailableError,
    RecordingTimeoutError,
    SilenceTimeoutError,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MicrophoneInfo:
    index: int
    name: str
    max_input_channels: int
    default_sample_rate: float


class AudioBackend(Protocol):
    def query_devices(self, device: int | None = None) -> Any: ...
    def check_input_settings(self, **kwargs: Any) -> Any: ...
    def rec(self, frames: int, *, samplerate: int, channels: int, dtype: str, device: int | None, blocking: bool) -> Any: ...
    def wait(self) -> None: ...
    def stop(self) -> None: ...


class SoundDeviceBackend:
    """Lazy adapter so the application can run without sounddevice installed."""
    def __init__(self) -> None:
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise MicrophoneUnavailableError("Microphone support requires the 'sounddevice' package.") from exc
        self._sd = sd

    def query_devices(self, device: int | None = None) -> Any:
        return self._sd.query_devices(device)

    def check_input_settings(self, **kwargs: Any) -> Any:
        return self._sd.check_input_settings(**kwargs)

    def rec(self, frames: int, **kwargs: Any) -> Any:
        return self._sd.rec(frames, **kwargs)

    def wait(self) -> None:
        self._sd.wait()

    def stop(self) -> None:
        self._sd.stop()


@dataclass(frozen=True)
class RecordingConfig:
    device_index: int | None = None
    sample_rate: int = 16000
    channels: int = 1
    start_timeout: float = 5.0
    silence_timeout: float = 1.2
    max_duration: float = 15.0
    silence_threshold: float = 0.015
    block_duration: float = 0.2

    def validate(self) -> None:
        if not 8000 <= self.sample_rate <= 48000:
            raise ValueError("sample_rate must be between 8000 and 48000")
        if self.channels not in {1, 2}:
            raise ValueError("channels must be 1 or 2")
        if not 0.5 <= self.start_timeout <= 30:
            raise ValueError("start_timeout is out of safe range")
        if not 0.2 <= self.silence_timeout <= 10:
            raise ValueError("silence_timeout is out of safe range")
        if not 1 <= self.max_duration <= 60:
            raise ValueError("max_duration is out of safe range")
        if not 0.001 <= self.silence_threshold <= 0.5:
            raise ValueError("silence_threshold is out of safe range")
        if not 0.05 <= self.block_duration <= 1:
            raise ValueError("block_duration is out of safe range")


class Microphone:
    def __init__(self, config: RecordingConfig, backend: AudioBackend | None = None):
        config.validate()
        self.config = config
        self.backend = backend or SoundDeviceBackend()
        self._stop_event = threading.Event()

    def request_stop(self) -> None:
        """Request cancellation of an active bounded recording."""
        self._stop_event.set()

    def clear_stop(self) -> None:
        self._stop_event.clear()

    def close(self) -> None:
        """Release/cancel any active capture without starting background work."""
        self.request_stop()
        stop = getattr(self.backend, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:
                logger.debug("Microphone backend stop failed during cleanup.", exc_info=False)

    def list_devices(self) -> list[MicrophoneInfo]:
        try:
            devices = self.backend.query_devices()
        except Exception as exc:  # noqa: BLE001
            raise MicrophoneUnavailableError("Could not query microphone devices.") from exc
        result: list[MicrophoneInfo] = []
        for index, device in enumerate(devices):
            channels = int(device.get("max_input_channels", 0))
            if channels > 0:
                result.append(MicrophoneInfo(index, str(device.get("name", f"Microphone {index}")), channels, float(device.get("default_samplerate", self.config.sample_rate))))
        return result

    def record(self) -> bytes:
        self.clear_stop()
        devices = self.list_devices()
        if not devices:
            raise MicrophoneUnavailableError("No microphone was found.")
        device_index = self.config.device_index
        if device_index is not None and not any(d.index == device_index for d in devices):
            raise MicrophoneDisconnectedError("Selected microphone is unavailable.")

        try:
            self.backend.check_input_settings(device=device_index, channels=self.config.channels, samplerate=self.config.sample_rate, dtype="float32")
        except Exception as exc:  # noqa: BLE001
            raise MicrophoneAccessError("Microphone access failed.") from exc

        # sounddevice recording is bounded by max_duration and blocks only while requested.
        block_frames = max(1, int(self.config.sample_rate * self.config.block_duration))
        blocks: list[Any] = []
        started = time.monotonic()
        speech_seen = False
        last_voice = started
        total_frames = 0
        try:
            while True:
                if self._stop_event.is_set():
                    raise AudioCaptureError("Recording stopped.")
                elapsed = time.monotonic() - started
                if not speech_seen and elapsed >= self.config.start_timeout:
                    raise SilenceTimeoutError("No speech was detected.")
                if elapsed >= self.config.max_duration:
                    if not speech_seen:
                        raise RecordingTimeoutError("Recording timed out before speech was detected.")
                    break
                data = self.backend.rec(block_frames, samplerate=self.config.sample_rate, channels=self.config.channels, dtype="float32", device=device_index, blocking=True)
                self.backend.wait()
                blocks.append(data)
                total_frames += block_frames
                rms = _rms(data)
                if rms >= self.config.silence_threshold:
                    speech_seen = True
                    last_voice = time.monotonic()
                elif speech_seen and time.monotonic() - last_voice >= self.config.silence_timeout:
                    break
        except (SilenceTimeoutError, RecordingTimeoutError):
            raise
        except Exception as exc:  # noqa: BLE001
            text = str(exc).lower()
            if "device" in text or "input" in text or "disconnected" in text:
                raise MicrophoneDisconnectedError("Microphone was disconnected during recording.") from exc
            raise AudioCaptureError("Audio capture failed.") from exc
        if not speech_seen or not blocks:
            raise SilenceTimeoutError("No speech was detected.")
        return _wav_bytes(blocks, self.config.sample_rate, self.config.channels)


def _rms(data: Any) -> float:
    try:
        values = data.reshape(-1)
        if len(values) == 0:
            return 0.0
        total = float((values * values).mean())
        return math.sqrt(max(total, 0.0))
    except Exception as exc:  # noqa: BLE001
        raise AudioCaptureError("Invalid audio data received from microphone.") from exc


def _wav_bytes(blocks: list[Any], sample_rate: int, channels: int) -> bytes:
    try:
        import numpy as np
        samples = np.concatenate(blocks, axis=0)
        samples = np.clip(samples, -1.0, 1.0)
        pcm = (samples * 32767).astype(np.int16).tobytes()
    except Exception as exc:  # noqa: BLE001
        raise AudioCaptureError("Could not encode captured audio.") from exc
    out = BytesIO()
    with wave.open(out, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return out.getvalue()
