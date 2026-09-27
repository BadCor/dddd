from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.config_manager import ConfigManager
from core.runtime_paths import bundled_root, executable_root, is_frozen, user_data_root


def test_build_spec_exists_and_contains_entrypoint():
    spec = (PROJECT_ROOT / "voice_assistant.spec").read_text(encoding="utf-8")
    assert '"main.py"' in spec
    assert '"config"' in spec
    assert 'name="VoiceAssistant"' in spec


def test_windows_build_scripts_exist():
    assert (PROJECT_ROOT / "scripts" / "build_windows.ps1").exists()
    assert (PROJECT_ROOT / "scripts" / "smoke_test_windows.ps1").exists()
    assert (PROJECT_ROOT / "requirements-build.txt").exists()


def test_default_config_is_bundled_source():
    assert (PROJECT_ROOT / "config" / "default_config.yaml").is_file()


def test_source_runtime_paths_are_project_based():
    assert is_frozen() is False
    assert bundled_root() == PROJECT_ROOT
    assert executable_root() == PROJECT_ROOT


def test_user_data_path_is_user_scoped(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path = user_data_root("Voice Assistant")
    assert path == tmp_path / "Voice Assistant"


def test_config_manager_keeps_source_user_config_separate_from_default(tmp_path):
    root = tmp_path / "project"
    (root / "config").mkdir(parents=True)
    default = (PROJECT_ROOT / "config" / "default_config.yaml").read_text(encoding="utf-8")
    (root / "config" / "default_config.yaml").write_text(default, encoding="utf-8")
    manager = ConfigManager(root)
    assert manager.default_config_path != manager.user_config_path
    assert manager.default_config_path.name == "default_config.yaml"
    assert manager.user_config_path.name == "config.yaml"


def test_no_secret_values_in_build_files():
    for relative in ("voice_assistant.spec", "scripts/build_windows.ps1", "README.md"):
        text = (PROJECT_ROOT / relative).read_text(encoding="utf-8").lower()
        assert "sk-" not in text
        assert "authorization: bearer" not in text
        assert "api_key =" not in text


def test_release_script_does_not_package_source_tests():
    text = (PROJECT_ROOT / "scripts" / "build_windows.ps1").read_text(encoding="utf-8")
    assert "tests" not in text.lower()


def test_requirements_contains_runtime_dependencies():
    text = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
    for package in ("sounddevice", "numpy", "PyYAML", "pyttsx3", "PySide6"):
        assert package.lower() in text.lower()
    assert "pyinstaller" in (PROJECT_ROOT / "requirements-build.txt").read_text(encoding="utf-8").lower()


def test_russian_parser_understands_file_folder_and_url_commands():
    from commands.parser import CommandParser
    parser = CommandParser()
    assert parser.parse("открой файл test.txt").action == {"action": "open_file", "target": "test.txt"}
    folder = parser.parse("открой папку Документы")
    assert folder.action is not None and folder.action["action"] == "open_folder"
    assert parser.parse("открой https://example.com").action == {"action": "open_url", "target": "https://example.com"}


def test_russian_parser_understands_approved_application():
    from commands.parser import CommandParser
    parser = CommandParser({"Chrome": "C:/Program Files/Chrome/chrome.exe"})
    result = parser.parse("запусти Chrome")
    assert result.action == {"action": "launch_application", "target": "Chrome"}


def test_speech_provider_defaults_to_russian_language():
    from speech.provider import OpenAITranscriptionProvider
    provider = OpenAITranscriptionProvider("gpt-transcribe", "https://example.com", "KEY")
    assert provider.language == "ru"
    body = provider._multipart_body("BOUNDARY", b"audio", "speech.wav")
    assert b'name="language"' in body
    assert b"\r\nru\r\n" in body


def test_russian_response_translation_for_safe_action():
    from actions.result import ActionResult
    from llm.pipeline import LLMRunResult
    from llm.result import LLMCommandResult, LLMStatus
    from localization import response_text
    result = LLMRunResult(
        LLMCommandResult(LLMStatus.ACTION, "ok"),
        ActionResult(True, "open_file", message="File opened successfully."),
    )
    assert response_text(result) == "Готово. Файл успешно открыт."
