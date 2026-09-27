from __future__ import annotations

import json
from pathlib import Path

import pytest

from actions.result import ActionResult
from llm.pipeline import LLMCommandPipeline
from llm.provider import LLMProvider
from llm.result import LLMCommandResult, LLMStatus, LLMProviderError, LLMTimeoutError
from llm.validator import validate_llm_response


class FakeProvider(LLMProvider):
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def generate_command(self, text, *, approved_apps):
        self.calls.append((text, dict(approved_apps)))
        if self.error:
            raise self.error
        return self.response


class RecordingManager:
    def __init__(self, result=None):
        self.received = []
        self.result = result or ActionResult(True, "open_folder", message="mocked")

    def execute(self, action):
        self.received.append(action)
        return self.result


@pytest.fixture
def apps():
    return {"chrome": r"C:\Program Files\Google\Chrome\chrome.exe"}


def action_response(action, target, message="Understood"):
    return json.dumps({"status": "action", "message": message, "action": {"action": action, "target": target}})


def test_valid_open_file_response(tmp_path, apps):
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    result = validate_llm_response(action_response("open_file", str(path)), approved_apps=apps)
    assert result.status is LLMStatus.ACTION
    assert result.action == {"action": "open_file", "target": str(path)}


def test_valid_open_folder_response(tmp_path, apps):
    result = validate_llm_response(action_response("open_folder", str(tmp_path)), approved_apps=apps)
    assert result.action == {"action": "open_folder", "target": str(tmp_path)}


def test_valid_url_response(apps):
    result = validate_llm_response(action_response("open_url", "https://github.com"), approved_apps=apps)
    assert result.action["action"] == "open_url"


def test_valid_approved_application_response(apps):
    result = validate_llm_response(action_response("launch_application", "Chrome"), approved_apps=apps)
    assert result.action == {"action": "launch_application", "target": "Chrome"}


def test_clarification_response(apps):
    raw = {"status": "needs_clarification", "message": "Application or folder?"}
    result = validate_llm_response(raw, approved_apps=apps)
    assert result.status is LLMStatus.NEEDS_CLARIFICATION
    assert result.action is None


def test_unsupported_response(apps):
    result = validate_llm_response({"status": "unsupported", "message": "I cannot do that."}, approved_apps=apps)
    assert result.status is LLMStatus.UNSUPPORTED


def test_malformed_json(apps):
    with pytest.raises(Exception, match="malformed JSON"):
        validate_llm_response("not-json", approved_apps=apps)


def test_unknown_action(apps, tmp_path):
    with pytest.raises(Exception, match="unsupported action"):
        validate_llm_response(action_response("run_command", str(tmp_path)), approved_apps=apps)


def test_missing_target(apps):
    with pytest.raises(Exception, match="target"):
        validate_llm_response(json.dumps({"status": "action", "message": "x", "action": {"action": "open_folder"}}), approved_apps=apps)


def test_wrong_field_type(apps):
    with pytest.raises(Exception, match="target"):
        validate_llm_response(json.dumps({"status": "action", "message": "x", "action": {"action": "open_folder", "target": 123}}), approved_apps=apps)


@pytest.mark.parametrize("payload", [
    action_response("open_file", "cmd /c whoami"),
    action_response("open_file", "powershell -Command Get-Process"),
])
def test_shell_and_powershell_attempts_are_rejected(payload, apps):
    with pytest.raises(Exception):
        validate_llm_response(payload, approved_apps=apps)


def test_arbitrary_executable_path_rejected(apps):
    with pytest.raises(Exception, match="approved application name"):
        validate_llm_response(action_response("launch_application", r"C:\Windows\System32\cmd.exe"), approved_apps=apps)


def test_unsafe_url_rejected(apps):
    with pytest.raises(Exception):
        validate_llm_response(action_response("open_url", "javascript:alert(1)"), approved_apps=apps)


def test_unexpected_fields_rejected(apps):
    with pytest.raises(Exception, match="unexpected fields"):
        validate_llm_response(json.dumps({"status": "unsupported", "message": "x", "command": "dir"}), approved_apps=apps)


def test_provider_timeout_falls_back_without_crash(apps):
    provider = FakeProvider(error=LLMTimeoutError("timeout"))
    manager = RecordingManager()
    pipeline = LLMCommandPipeline(provider, apps=apps, manager=manager)
    result = pipeline.handle("Hello")
    assert result.used_fallback is True
    assert result.command.status in {LLMStatus.UNSUPPORTED, LLMStatus.INVALID}
    assert manager.received == []


def test_provider_network_failure_falls_back(apps):
    provider = FakeProvider(error=LLMProviderError("network"))
    manager = RecordingManager()
    result = LLMCommandPipeline(provider, apps=apps, manager=manager).handle("Open Chrome")
    assert result.used_fallback is True
    assert result.command.status is LLMStatus.ACTION
    assert manager.received == [{"action": "launch_application", "target": "Chrome"}]


def test_missing_api_key_is_provider_configuration_error(monkeypatch):
    from llm.provider import OpenAICompatibleProvider
    monkeypatch.delenv("TEST_ASSISTANT_KEY", raising=False)
    provider = OpenAICompatibleProvider("test-model", "http://127.0.0.1:9", "TEST_ASSISTANT_KEY")
    with pytest.raises(Exception, match="API key"):
        provider.generate_command("Hello", approved_apps={})


def test_invalid_llm_output_never_reaches_manager(apps):
    provider = FakeProvider(response=action_response("run_command", "dir"))
    manager = RecordingManager()
    result = LLMCommandPipeline(provider, apps=apps, manager=manager).handle("Do something")
    assert result.used_fallback is True
    assert manager.received == []


def test_valid_llm_output_reaches_existing_action_manager(apps):
    provider = FakeProvider(response=action_response("launch_application", "Chrome"))
    manager = RecordingManager(ActionResult(True, "launch_application", message="mocked"))
    result = LLMCommandPipeline(provider, apps=apps, manager=manager).handle("Could you please open Chrome?")
    assert result.command.status is LLMStatus.ACTION
    assert manager.received == [{"action": "launch_application", "target": "Chrome"}]
    assert result.action_result.success is True


def test_no_direct_windows_execution_in_parser_layer(apps):
    provider = FakeProvider(response=action_response("open_url", "https://example.com"))
    manager = RecordingManager()
    pipeline = LLMCommandPipeline(provider, apps=apps, manager=manager)
    result = pipeline.handle("Open the website")
    assert result.action_result.success is True
    assert manager.received == [{"action": "open_url", "target": "https://example.com"}]
