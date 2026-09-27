from __future__ import annotations

from pathlib import Path

import pytest

from actions.manager import ActionManager
from actions.result import ActionResult
from commands.parser import CommandParser
from commands.pipeline import CommandPipeline
from commands.result import CommandStatus


class TestParser:
    @pytest.fixture
    def parser(self):
        return CommandParser({"chrome": r"C:\Program Files\Google\Chrome\chrome.exe"})

    def test_open_existing_file_command(self, parser, tmp_path):
        path = tmp_path / "notes.txt"
        path.write_text("hello", encoding="utf-8")
        result = parser.parse(f"Open file {path}")
        assert result.status is CommandStatus.ACTION
        assert result.action == {"action": "open_file", "target": str(path)}

    def test_open_existing_folder_command(self, parser, tmp_path):
        result = parser.parse(f"please open folder {tmp_path}")
        assert result.action == {"action": "open_folder", "target": str(tmp_path)}

    @pytest.mark.parametrize("command", [
        "Open https://github.com",
        "please open https://github.com",
        "could you open https://github.com",
    ])
    def test_open_url_variations(self, parser, command):
        result = parser.parse(command)
        assert result.action == {"action": "open_url", "target": "https://github.com"}

    def test_launch_approved_application(self, parser):
        result = parser.parse("Open Chrome")
        assert result.action == {"action": "launch_application", "target": "Chrome"}

    def test_launch_variations(self, parser):
        for command in ("launch Chrome", "please start Chrome", "could you run Chrome"):
            result = parser.parse(command)
            assert result.status is CommandStatus.ACTION
            assert result.action["action"] == "launch_application"

    def test_polite_russian_application_requests(self):
        parser = CommandParser({"телеграм": r"C:\\Apps\\Telegram.exe"})
        for command in (
            "открой, пожалуйста, Телеграм",
            "можешь открыть Телеграм",
            "открой мне Телеграм пожалуйста",
            "Телеграм",
        ):
            result = parser.parse(command)
            assert result.status is CommandStatus.ACTION
            assert result.action == {"action": "launch_application", "target": "Телеграм"}

    def test_downloads_folder_variations(self, parser):
        expected = str(Path.home() / "Downloads")
        for command in ("open Downloads", "please open Downloads", "could you open my Downloads folder"):
            result = parser.parse(command)
            assert result.status is CommandStatus.ACTION
            assert result.action == {"action": "open_folder", "target": expected}

    @pytest.mark.parametrize("command", ["", "   ", None])
    def test_empty_input(self, parser, command):
        result = parser.parse(command)
        assert result.status is CommandStatus.INVALID

    @pytest.mark.parametrize("command", ["Hello", "asdfgh", "Do something", "Run whatever"])
    def test_unknown_commands(self, parser, command):
        result = parser.parse(command)
        assert result.status in {CommandStatus.UNSUPPORTED, CommandStatus.INVALID}

    @pytest.mark.parametrize("command", ["Open", "please open", "launch", "run"])
    def test_incomplete_command(self, parser, command):
        result = parser.parse(command)
        assert result.status is CommandStatus.INVALID

    def test_ambiguous_command_does_not_execute(self, parser):
        result = parser.parse("Open Minecraft")
        assert result.status is CommandStatus.NEEDS_CLARIFICATION
        assert result.action is None
        assert "application" in result.message.lower()

    def test_ambiguous_when_app_and_folder_exist(self, tmp_path, monkeypatch):
        minecraft = tmp_path / "Minecraft"
        minecraft.mkdir()
        monkeypatch.chdir(tmp_path)
        parser = CommandParser({"minecraft": str(tmp_path / "minecraft.exe")})
        result = parser.parse("Open Minecraft")
        assert result.status is CommandStatus.NEEDS_CLARIFICATION

    def test_invalid_target_is_passed_to_stage2_for_validation(self, parser):
        result = parser.parse("open file bad\x00path")
        assert result.status is CommandStatus.ACTION
        assert result.action["action"] == "open_file"


class RecordingManager:
    def __init__(self):
        self.received = []

    def execute(self, action):
        self.received.append(action)
        return ActionResult(True, action["action"], message="mocked")


def test_pipeline_uses_stage2_manager():
    manager = RecordingManager()
    pipeline = CommandPipeline({"chrome": "x"}, manager=manager)
    result = pipeline.handle("Open Chrome")
    assert result.action_result.success is True
    assert manager.received == [{"action": "launch_application", "target": "Chrome"}]


def test_pipeline_does_not_execute_on_clarification(monkeypatch):
    manager = RecordingManager()
    pipeline = CommandPipeline({}, manager=manager)
    result = pipeline.handle("Open Minecraft")
    assert result.command.status is CommandStatus.NEEDS_CLARIFICATION
    assert result.action_result is None
    assert manager.received == []


def test_parser_does_not_call_action_manager_or_windows(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(ActionManager, "execute", lambda *args, **kwargs: called.append(True))
    parser = CommandParser()
    result = parser.parse(f"open folder {tmp_path}")
    assert result.status is CommandStatus.ACTION
    assert called == []
