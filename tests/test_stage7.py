from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent


def test_stage7_files_exist():
    for relative in (
        "gui/__init__.py",
        "gui/main_window.py",
        "gui/workers.py",
        "gui/widgets.py",
    ):
        assert (ROOT / relative).is_file()


def test_gui_has_no_direct_windows_action_calls():
    source = (ROOT / "gui").read_text(encoding="utf-8") if False else ""
    for path in (ROOT / "gui").glob("*.py"):
        source += path.read_text(encoding="utf-8")
    forbidden = ("subprocess", "os.system", "Popen(", "PowerShell", "winsound", "ActionManager(")
    assert not any(token in source for token in forbidden)


def test_gui_routes_typed_input_to_existing_command_pipeline():
    source = (ROOT / "gui/main_window.py").read_text(encoding="utf-8")
    assert "self.command_pipeline.handle(self.text)" not in source  # worker owns it
    worker = (ROOT / "gui/workers.py").read_text(encoding="utf-8")
    assert "self.command_pipeline.handle(self.text)" in worker


def test_gui_routes_voice_to_existing_speech_pipeline():
    source = (ROOT / "gui/workers.py").read_text(encoding="utf-8")
    assert "self.speech_pipeline.listen_once()" in source
    assert "response_text(result.command)" in source


def test_requirements_contains_pyside6():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "PySide6" in requirements


def test_stage7_qt_import_is_available_or_explicitly_missing():
    pytest.importorskip("PySide6")
