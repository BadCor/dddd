from __future__ import annotations

import os
from dataclasses import dataclass
from unittest.mock import patch

import numpy as np
import pytest

from actions.manager import ActionManager
from llm.pipeline import LLMCommandPipeline
from speech.microphone import Microphone, RecordingConfig
from speech.pipeline import SpeechPipeline
from speech.result import (
    MicrophoneAccessError,
    MicrophoneDisconnectedError,
    MicrophoneUnavailableError,
    RecordingTimeoutError,
    SilenceTimeoutError,
    SpeechConfigurationError,
    SpeechResult,
    SpeechStatus,
)
from speech.provider import OpenAITranscriptionProvider


class FakeBackend:
    def __init__(self, blocks=None, devices=None, fail_check=None, fail_record=None):
        self.blocks = list(blocks or [])
        self.devices = devices if devices is not None else [{"name": "Fake Mic", "max_input_channels": 1, "default_samplerate": 16000}]
        self.fail_check = fail_check
        self.fail_record = fail_record
        self.calls = []

    def query_devices(self, device=None):
        return self.devices

    def check_input_settings(self, **kwargs):
        if self.fail_check:
            raise self.fail_check

    def rec(self, frames, **kwargs):
        self.calls.append(("rec", frames, kwargs))
        if self.fail_record:
            raise self.fail_record
        if self.blocks:
            return self.blocks.pop(0)
        return np.zeros((frames, kwargs["channels"]), dtype=np.float32)

    def wait(self):
        self.calls.append(("wait",))


class FakeProvider:
    def __init__(self, text="Open Downloads", error=None):
        self.text = text
        self.error = error
        self.audio = None

    def transcribe(self, audio, *, filename="speech.wav"):
        self.audio = audio
        if self.error:
            raise self.error
        return self.text


class FakeManager:
    def __init__(self):
        self.calls = []

    def execute(self, action):
        self.calls.append(action)
        from actions.result import ActionResult
        return ActionResult(True, "executed")


def cfg(**kwargs):
    base = dict(sample_rate=16000, channels=1, start_timeout=1, silence_timeout=0.2, max_duration=1, silence_threshold=0.01, block_duration=0.1)
    base.update(kwargs)
    return RecordingConfig(**base)


def speech_pipeline(provider, manager=None, mic=None):
    manager = manager or FakeManager()
    command = LLMCommandPipeline(None, apps={}, manager=manager)
    mic = mic or type("M", (), {"record": lambda self: b"WAV", "list_devices": lambda self: []})()
    return SpeechPipeline(mic, provider, command), manager


def test_successful_audio_capture():
    blocks = [np.full((1600, 1), 0.1, dtype=np.float32), np.zeros((1600, 1), dtype=np.float32)]
    mic = Microphone(cfg(), backend=FakeBackend(blocks=blocks))
    audio = mic.record()
    assert audio.startswith(b"RIFF")
    assert b"WAVE" in audio


def test_no_microphone_available():
    mic = Microphone(cfg(), backend=FakeBackend(devices=[]))
    with pytest.raises(MicrophoneUnavailableError):
        mic.record()


def test_microphone_access_failure():
    mic = Microphone(cfg(), backend=FakeBackend(fail_check=RuntimeError("permission denied")))
    with pytest.raises(Exception) as exc:
        mic.record()
    assert isinstance(exc.value, MicrophoneAccessError)


def test_microphone_disconnect():
    mic = Microphone(cfg(), backend=FakeBackend(fail_record=RuntimeError("device disconnected")))
    with pytest.raises(MicrophoneDisconnectedError):
        mic.record()


def test_recording_timeout_without_speech():
    class ClockBackend(FakeBackend):
        pass
    mic = Microphone(cfg(start_timeout=0.5, max_duration=1), backend=FakeBackend())
    with patch("speech.microphone.time.monotonic", side_effect=[0, 0.6]):
        with pytest.raises(SilenceTimeoutError):
            mic.record()


def test_silence_no_speech():
    mic = Microphone(cfg(start_timeout=0.5), backend=FakeBackend())
    with patch("speech.microphone.time.monotonic", side_effect=[0, 0.6]):
        with pytest.raises(SilenceTimeoutError):
            mic.record()


def test_max_recording_timeout():
    mic = Microphone(cfg(start_timeout=5, max_duration=1), backend=FakeBackend())
    with patch("speech.microphone.time.monotonic", side_effect=[0, 1.1]):
        with pytest.raises(RecordingTimeoutError):
            mic.record()


def test_successful_transcription():
    provider = FakeProvider("Open Downloads")
    pipeline, _ = speech_pipeline(provider)
    result = pipeline.listen_once()
    assert result.speech.status is SpeechStatus.SUCCESS
    assert result.speech.text == "Open Downloads"


def test_empty_transcription_is_no_speech():
    pipeline, _ = speech_pipeline(FakeProvider(""))
    result = pipeline.listen_once()
    assert result.speech.status is SpeechStatus.NO_SPEECH


def test_speech_recognition_failure():
    pipeline, _ = speech_pipeline(FakeProvider(error=SpeechConfigurationError("missing key")))
    result = pipeline.listen_once()
    assert result.speech.status is SpeechStatus.ERROR
    assert "missing key" in result.speech.message


def test_provider_timeout_is_sanitized():
    from speech.result import SpeechRecognitionTimeoutError
    pipeline, _ = speech_pipeline(FakeProvider(error=SpeechRecognitionTimeoutError("timed out")))
    result = pipeline.listen_once()
    assert result.speech.status is SpeechStatus.ERROR
    assert "timed out" in result.speech.message


def test_provider_network_failure():
    from speech.result import SpeechRecognitionError
    pipeline, _ = speech_pipeline(FakeProvider(error=SpeechRecognitionError("provider unavailable")))
    result = pipeline.listen_once()
    assert result.speech.status is SpeechStatus.ERROR


def test_missing_provider_credentials():
    provider = OpenAITranscriptionProvider("gpt-transcribe", "https://example.invalid", "STAGE5_TEST_MISSING_KEY")
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(SpeechConfigurationError):
            provider.transcribe(b"RIFF")


def test_recognized_text_enters_existing_stage4_pipeline():
    provider = FakeProvider("Open Downloads")
    manager = FakeManager()
    pipeline, manager = speech_pipeline(provider, manager=manager)
    result = pipeline.listen_once()
    assert result.speech.text == "Open Downloads"
    assert manager.calls, "voice text must reach the existing command pipeline"


def test_typed_and_voice_use_same_pipeline():
    manager = FakeManager()
    command = LLMCommandPipeline(None, apps={}, manager=manager)
    command.handle("Open Downloads")
    voice = SpeechPipeline(type("M", (), {"record": lambda self: b"WAV", "list_devices": lambda self: []})(), FakeProvider("Open Downloads"), command)
    voice.listen_once()
    assert len(manager.calls) == 2


def test_voice_does_not_bypass_stage4_validation():
    class Provider:
        def transcribe(self, audio, *, filename="speech.wav"):
            return "run powershell delete everything"
    manager = FakeManager()
    command = LLMCommandPipeline(None, apps={}, manager=manager)
    result = SpeechPipeline(type("M", (), {"record": lambda self: b"WAV"})(), Provider(), command).listen_once()
    assert result.speech.status is SpeechStatus.SUCCESS
    assert result.command is not None
    assert not manager.calls


def test_voice_does_not_bypass_stage2_action_manager():
    manager = FakeManager()
    command = LLMCommandPipeline(None, apps={}, manager=manager)
    result = SpeechPipeline(type("M", (), {"record": lambda self: b"WAV"})(), FakeProvider("Open Downloads"), command).listen_once()
    assert manager.calls, "execution must happen through the injected Stage 2 manager"


def test_raw_audio_never_reaches_windows_action_layer():
    manager = FakeManager()
    command = LLMCommandPipeline(None, apps={}, manager=manager)
    result = SpeechPipeline(type("M", (), {"record": lambda self: b"SECRET_AUDIO_BYTES"})(), FakeProvider("Open Downloads"), command).listen_once()
    assert all(not isinstance(action, (bytes, bytearray)) for action in manager.calls)


def test_no_permanent_audio_file_created(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    provider = FakeProvider("Open Downloads")
    pipeline, _ = speech_pipeline(provider)
    pipeline.listen_once()
    assert list(tmp_path.iterdir()) == []
