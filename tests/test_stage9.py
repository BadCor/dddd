from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm.validator import validate_llm_response
from llm.result import LLMStatus
from user_data import (
    JsonStorage,
    MemoryCategory,
    MemoryManager,
    MemoryOperation,
    MemoryOperationType,
    SettingsManager,
)


def test_settings_persistence(tmp_path):
    storage = JsonStorage(tmp_path / "user_data.json")
    settings = SettingsManager(storage)
    settings.save("tts_enabled", False)
    settings.save("tts_rate", 220)
    assert SettingsManager(storage).get("tts_enabled") is False
    assert SettingsManager(storage).get("tts_rate") == 220


def test_settings_loading_and_runtime_overlay(tmp_path):
    storage = JsonStorage(tmp_path / "user_data.json")
    settings = SettingsManager(storage)
    settings.update({"tts_volume": 0.5, "microphone_index": 2, "llm_provider": "none", "llm_model": "test-model"})
    config = {"tts": {"enabled": True, "volume": 1.0}, "speech": {"microphone_index": None}, "llm": {"provider": "openai", "model": "old"}}
    runtime = settings.apply_to_config(config)
    assert runtime["tts"]["volume"] == 0.5
    assert runtime["speech"]["microphone_index"] == 2
    assert runtime["llm"]["provider"] == "none"
    assert config["tts"]["volume"] == 1.0


def test_corrupted_settings_recovery(tmp_path):
    path = tmp_path / "user_data.json"
    path.write_text("{broken", encoding="utf-8")
    settings = SettingsManager(JsonStorage(path))
    assert settings.all() == {}
    recovered = json.loads(path.read_text(encoding="utf-8"))
    assert recovered["settings"] == {}


def test_memory_save_and_retrieve(tmp_path):
    manager = MemoryManager(JsonStorage(tmp_path / "user_data.json"), approved_apps={"Chrome": "x"})
    saved = manager.apply(MemoryOperation(MemoryOperationType.SAVE, MemoryCategory.PREFERRED_APPLICATION, "default", "Chrome"))
    assert saved.success
    found = manager.get(MemoryCategory.PREFERRED_APPLICATION)
    assert found.success and found.value == "Chrome"


def test_memory_update(tmp_path):
    manager = MemoryManager(JsonStorage(tmp_path / "user_data.json"))
    manager.apply(MemoryOperation(MemoryOperationType.SAVE, MemoryCategory.ASSISTANT_PREFERENCE, "response_style", "short"))
    result = manager.apply(MemoryOperation(MemoryOperationType.UPDATE, MemoryCategory.ASSISTANT_PREFERENCE, "response_style", "detailed"))
    assert result.success
    assert manager.get(MemoryCategory.ASSISTANT_PREFERENCE, "response_style").value == "detailed"


def test_memory_delete(tmp_path):
    manager = MemoryManager(JsonStorage(tmp_path / "user_data.json"))
    manager.apply(MemoryOperation(MemoryOperationType.SAVE, MemoryCategory.ASSISTANT_PREFERENCE, "preferred_language", "ru"))
    assert manager.apply(MemoryOperation(MemoryOperationType.DELETE, MemoryCategory.ASSISTANT_PREFERENCE, "preferred_language")).success
    assert not manager.get(MemoryCategory.ASSISTANT_PREFERENCE, "preferred_language").success


def test_memory_clear(tmp_path):
    manager = MemoryManager(JsonStorage(tmp_path / "user_data.json"))
    manager.apply(MemoryOperation(MemoryOperationType.SAVE, MemoryCategory.ASSISTANT_PREFERENCE, "response_style", "short"))
    assert manager.clear_supported().success
    assert not manager.get(MemoryCategory.ASSISTANT_PREFERENCE, "response_style").success


def test_memory_is_explicit_only(tmp_path):
    manager = MemoryManager(JsonStorage(tmp_path / "user_data.json"))
    assert manager.get(MemoryCategory.ASSISTANT_PREFERENCE, "response_style").success is False
    assert not (tmp_path / "user_data.json").exists()


def test_secret_rejection(tmp_path):
    manager = MemoryManager(JsonStorage(tmp_path / "user_data.json"))
    result = manager.apply(MemoryOperation(MemoryOperationType.SAVE, MemoryCategory.ASSISTANT_PREFERENCE, "response_style", "my password is 123"))
    assert result.success is False
    settings = SettingsManager(JsonStorage(tmp_path / "settings.json"))
    with pytest.raises(ValueError):
        settings.save("api_key", "secret")


def test_invalid_memory_data_rejection(tmp_path):
    manager = MemoryManager(JsonStorage(tmp_path / "user_data.json"))
    assert not manager.apply(MemoryOperation(MemoryOperationType.SAVE, MemoryCategory.ASSISTANT_PREFERENCE, "unknown", "x")).success
    assert not manager.apply(MemoryOperation(MemoryOperationType.SAVE, MemoryCategory.ASSISTANT_PREFERENCE, "response_style", "")).success


def test_stored_folder_path_validation(tmp_path):
    folder = tmp_path / "Project"
    folder.mkdir()
    manager = MemoryManager(JsonStorage(tmp_path / "user_data.json"))
    assert manager.apply(MemoryOperation(MemoryOperationType.SAVE, MemoryCategory.PREFERRED_FOLDER, "default", str(folder))).success
    assert manager.validate_for_use(MemoryCategory.PREFERRED_FOLDER).success
    folder.rmdir()
    assert manager.validate_for_use(MemoryCategory.PREFERRED_FOLDER).success is False


def test_stored_application_validation(tmp_path):
    manager = MemoryManager(JsonStorage(tmp_path / "user_data.json"), approved_apps={"Chrome": "x"})
    assert manager.apply(MemoryOperation(MemoryOperationType.SAVE, MemoryCategory.PREFERRED_APPLICATION, "default", "Chrome")).success
    manager.approved_apps.clear()
    assert manager.validate_for_use(MemoryCategory.PREFERRED_APPLICATION).success is False


def test_restart_persistence(tmp_path):
    path = tmp_path / "user_data.json"
    manager = MemoryManager(JsonStorage(path))
    manager.apply(MemoryOperation(MemoryOperationType.SAVE, MemoryCategory.ASSISTANT_PREFERENCE, "confirmation_mode", "ask"))
    restarted = MemoryManager(JsonStorage(path))
    assert restarted.get(MemoryCategory.ASSISTANT_PREFERENCE, "confirmation_mode").value == "ask"


def test_llm_memory_operation_validation():
    raw = {
        "status": "memory",
        "message": "Saved your preference.",
        "memory": {"operation": "save", "category": "assistant_preference", "key": "response_style", "value": "short"},
    }
    result = validate_llm_response(raw, approved_apps={})
    assert result.status is LLMStatus.MEMORY
    assert result.memory["operation"] == "save"


def test_llm_memory_rejects_secret_and_extra_fields():
    raw = {
        "status": "memory",
        "message": "x",
        "memory": {"operation": "save", "category": "assistant_preference", "key": "api_key", "value": "secret"},
    }
    with pytest.raises(Exception):
        validate_llm_response(raw, approved_apps={})
    raw["memory"]["key"] = "response_style"
    raw["memory"]["extra"] = "bad"
    with pytest.raises(Exception):
        validate_llm_response(raw, approved_apps={})


def test_explicit_memory_parser():
    from user_data.memory import parse_explicit_memory_request
    op = parse_explicit_memory_request("Remember that I use Chrome", {"Chrome": "x"})
    assert op is not None
    assert op.category is MemoryCategory.PREFERRED_APPLICATION
    assert op.value == "Chrome"
    assert parse_explicit_memory_request("What is the weather?") is None


def test_gui_stage9_integration_is_small_and_backgrounded():
    root = Path(__file__).resolve().parent.parent
    gui = (root / "gui/main_window.py").read_text(encoding="utf-8")
    workers = (root / "gui/workers.py").read_text(encoding="utf-8")
    main = (root / "main.py").read_text(encoding="utf-8")
    assert "Clear Memory" in gui and "Settings" in gui
    assert "settings_manager.save(\"tts_enabled\"" in gui
    assert "settings_manager.save(\"microphone_index\"" in gui
    assert "MemoryAwareCommandPipeline" in main
    assert "QThread" in workers


def test_memory_layer_never_executes_windows_actions():
    root = Path(__file__).resolve().parent.parent
    source = "".join(path.read_text(encoding="utf-8") for path in (root / "user_data").glob("*.py"))
    assert not any(token in source for token in ("subprocess", "os.system", "Popen(", "PowerShell", "ActionManager(", ".execute("))


def test_memory_pipeline_executes_memory_without_action_manager(tmp_path):
    from commands.memory_pipeline import MemoryAwareCommandPipeline
    from llm.pipeline import LLMRunResult
    from llm.result import LLMCommandResult

    class Base:
        apps = {"Chrome": "C:\\approved\\chrome.exe"}
        def handle(self, text):
            return LLMRunResult(LLMCommandResult(LLMStatus.UNSUPPORTED, "Not an action."))

    memory = MemoryManager(JsonStorage(tmp_path / "user_data.json"), approved_apps={"Chrome": "x"})
    pipeline = MemoryAwareCommandPipeline(Base(), memory)
    result = pipeline.handle("Remember that I use Chrome")
    assert result.command.status is LLMStatus.ACTION
    assert memory.get(MemoryCategory.PREFERRED_APPLICATION).value == "Chrome"
