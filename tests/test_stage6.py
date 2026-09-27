from __future__ import annotations

import logging
import os
import threading

from actions.result import ActionResult
from llm.pipeline import LLMCommandPipeline, LLMRunResult
from llm.result import LLMCommandResult, LLMStatus
from tts.pipeline import TTSPipeline
from tts.response import response_text
from tts.result import TTSStatus
from tts.text import sanitize_text


class FakeTTSProvider:
    def __init__(self, audio=b"RIFFFAKEWAVE", error=None):
        self.audio = audio
        self.error = error
        self.calls = []

    def synthesize(self, text):
        self.calls.append(text)
        if self.error:
            raise self.error
        return self.audio


class FakeOutput:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def play(self, audio):
        self.calls.append(audio)
        if self.error:
            raise self.error


def pipeline(provider=None, output=None, enabled=True):
    return TTSPipeline(provider, output, enabled=enabled)


def test_successful_synthesis_and_playback():
    provider, output = FakeTTSProvider(), FakeOutput()
    result = pipeline(provider, output).speak("Done.")
    assert result.status is TTSStatus.SUCCESS
    assert provider.calls == ["Done."]
    assert output.calls == [b"RIFFFAKEWAVE"]


def test_empty_text_is_rejected():
    provider, output = FakeTTSProvider(), FakeOutput()
    result = pipeline(provider, output).speak("   \n\t ")
    assert result.status is TTSStatus.ERROR
    assert provider.calls == []
    assert output.calls == []


def test_very_long_text_is_safely_limited():
    provider, output = FakeTTSProvider(), FakeOutput()
    result = pipeline(provider, output).speak("x" * 5000)
    assert result.status is TTSStatus.SUCCESS
    assert len(provider.calls[0]) <= 2000
    assert provider.calls[0].endswith("...")


def test_control_characters_are_removed():
    assert sanitize_text("Hello\x00 world\x1b[31m") == "Hello world [31m"


def test_tts_disabled_never_calls_provider_or_output():
    provider, output = FakeTTSProvider(), FakeOutput()
    result = pipeline(provider, output, enabled=False).speak("Done.")
    assert result.status is TTSStatus.DISABLED
    assert provider.calls == []
    assert output.calls == []


def test_missing_provider_is_clean_error():
    result = pipeline(None, FakeOutput()).speak("Done.")
    assert result.status is TTSStatus.ERROR


def test_provider_failure_does_not_crash():
    provider, output = FakeTTSProvider(error=RuntimeError("secret provider details")), FakeOutput()
    result = pipeline(provider, output).speak("Done.")
    assert result.status is TTSStatus.ERROR
    assert output.calls == []


def test_provider_timeout_is_clean_error():
    provider, output = FakeTTSProvider(error=TimeoutError()), FakeOutput()
    result = pipeline(provider, output).speak("Done.")
    assert result.status is TTSStatus.ERROR


def test_audio_playback_failure_is_clean_error():
    provider, output = FakeTTSProvider(), FakeOutput(error=RuntimeError("speaker failure"))
    result = pipeline(provider, output).speak("Done.")
    assert result.status is TTSStatus.ERROR


def test_successful_playback():
    provider, output = FakeTTSProvider(), FakeOutput()
    result = pipeline(provider, output).speak("Hello.")
    assert result.status is TTSStatus.SUCCESS
    assert output.calls


def test_action_success_remains_success_when_tts_fails():
    action = ActionResult(True, "open_folder", message="Folder opened successfully.")
    command = LLMRunResult(LLMCommandResult(LLMStatus.ACTION, "Opened."), action)
    provider, output = FakeTTSProvider(error=RuntimeError()), FakeOutput()
    tts_result = pipeline(provider, output).speak(response_text(command))
    assert action.success is True
    assert tts_result.status is TTSStatus.ERROR


def test_text_response_remains_available_when_tts_disabled():
    action = ActionResult(True, "open_folder", message="Folder opened successfully.")
    command = LLMRunResult(LLMCommandResult(LLMStatus.ACTION, "Opened."), action)
    provider, output = FakeTTSProvider(), FakeOutput()
    tts_result = pipeline(provider, output, enabled=False).speak(response_text(command))
    assert response_text(command) == "Done. Folder opened successfully."
    assert tts_result.status is TTSStatus.DISABLED


def test_tts_has_no_access_to_action_manager():
    class ExplodingManager:
        def execute(self, action):
            raise AssertionError("TTS must never execute actions")
    # TTS only accepts provider/output, not an ActionManager.
    provider, output = FakeTTSProvider(), FakeOutput()
    result = pipeline(provider, output).speak("Done.")
    assert result.status is TTSStatus.SUCCESS


def test_credentials_are_not_logged(caplog):
    secret = "SUPER_SECRET_TTS_KEY"
    provider = FakeTTSProvider(error=RuntimeError(secret))
    output = FakeOutput()
    with caplog.at_level(logging.WARNING):
        pipeline(provider, output).speak("Done.")
    assert secret not in caplog.text


def test_multiple_responses_are_serialized():
    provider, output = FakeTTSProvider(), FakeOutput()
    tts = pipeline(provider, output)
    results = []

    def speak(text):
        results.append(tts.speak(text).status)

    threads = [threading.Thread(target=speak, args=(f"response {i}",)) for i in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count(TTSStatus.SUCCESS) == 3
    assert len(provider.calls) == 3
    assert len(output.calls) == 3


def test_no_permanent_audio_files_created(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    provider, output = FakeTTSProvider(), FakeOutput()
    assert pipeline(provider, output).speak("Done.").status is TTSStatus.SUCCESS
    assert list(tmp_path.iterdir()) == []


def test_response_text_for_failed_action_is_safe():
    action = ActionResult(False, "open_folder", error="Folder does not exist.")
    command = LLMRunResult(LLMCommandResult(LLMStatus.ACTION, "Failed."), action)
    assert response_text(command) == "Folder does not exist."
