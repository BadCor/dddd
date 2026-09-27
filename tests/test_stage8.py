from __future__ import annotations

import os
from pathlib import Path
from threading import Event

from actions.manager import ActionManager
from discovery.application_discovery import ApplicationDiscovery
from discovery.file_discovery import FileDiscovery
from discovery.folder_discovery import FolderDiscovery
from discovery.manager import DiscoveryManager
from commands.discovery_pipeline import DiscoveryAwareCommandPipeline
from discovery.models import DiscoveryKind, DiscoveryStatus
from llm.pipeline import LLMCommandPipeline
from llm.result import LLMCommandResult, LLMStatus


class FakeProvider:
    def generate_command(self, text, approved_apps):
        return {"status": "needs_clarification", "message": "Need a target."}


def test_file_discovery(tmp_path):
    (tmp_path / "project.py").write_text("print(1)", encoding="utf-8")
    result = FileDiscovery([tmp_path], max_depth=2, max_results=10, timeout=1).search("project")
    assert result.status is DiscoveryStatus.SUCCESS
    assert result.candidates[0].name == "project.py"
    assert result.candidates[0].size is not None


def test_folder_discovery(tmp_path):
    (tmp_path / "Minecraft").mkdir()
    result = FolderDiscovery([tmp_path], max_depth=2, max_results=10, timeout=1).search("minecraft")
    assert result.status is DiscoveryStatus.SUCCESS
    assert result.candidates[0].path.endswith("Minecraft")


def test_application_discovery_start_menu_mock(tmp_path, monkeypatch):
    programs = tmp_path / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    programs.mkdir(parents=True)
    shortcut = programs / "Chrome.lnk"
    shortcut.write_text("placeholder", encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("PROGRAMDATA", raising=False)
    result = ApplicationDiscovery({"chrome": "C:\\approved\\chrome.exe"}, registry=False).search("Chrome")
    assert result.status is DiscoveryStatus.SUCCESS
    assert result.candidates[0].name == "Chrome"
    assert result.candidates[0].approved is True


def test_configured_search_roots(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    (root / "demo.txt").write_text("x", encoding="utf-8")
    manager = DiscoveryManager({"search_roots": {"files": [str(root)], "folders": [str(tmp_path)]}, "timeout": 1}, {})
    result = manager.search("demo", DiscoveryKind.FILE)
    assert result.candidates[0].path.endswith("demo.txt")


def test_result_limit(tmp_path):
    for i in range(10):
        (tmp_path / f"note-{i}.txt").write_text("x", encoding="utf-8")
    result = FileDiscovery([tmp_path], max_results=3, timeout=1).search("note")
    assert len(result.candidates) == 3
    assert result.truncated is True


def test_invalid_and_missing_roots_return_no_results(tmp_path):
    missing = tmp_path / "missing"
    result = FileDiscovery([missing], timeout=1).search("x")
    assert result.status is DiscoveryStatus.NO_RESULTS
    result2 = FolderDiscovery([missing], timeout=1).search("x")
    assert result2.status is DiscoveryStatus.NO_RESULTS


def test_permission_errors_are_skipped(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    original = os.scandir
    def fake_scandir(path):
        if Path(path) == root:
            raise PermissionError("denied")
        return original(path)
    monkeypatch.setattr(os, "scandir", fake_scandir)
    result = FileDiscovery([root], timeout=1).search("x")
    assert result.status is DiscoveryStatus.NO_RESULTS


def test_ambiguous_results_are_returned_without_selection(tmp_path):
    (tmp_path / "project-a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "project-b.txt").write_text("b", encoding="utf-8")
    result = FileDiscovery([tmp_path], timeout=1).search("project")
    assert result.status is DiscoveryStatus.AMBIGUOUS
    assert len(result.candidates) == 2


def test_no_results_handling(tmp_path):
    result = FileDiscovery([tmp_path], timeout=1).search("does-not-exist")
    assert result.status is DiscoveryStatus.NO_RESULTS
    assert result.candidates == ()


def test_discovery_never_executes_actions(tmp_path, monkeypatch):
    (tmp_path / "safe.txt").write_text("x", encoding="utf-8")
    called = []
    monkeypatch.setattr(ActionManager, "execute", lambda self, action: called.append(action))
    result = FileDiscovery([tmp_path], timeout=1).search("safe")
    assert result.candidates
    assert called == []


def test_action_manager_remains_execution_layer(tmp_path):
    (tmp_path / "safe.txt").write_text("x", encoding="utf-8")
    manager = ActionManager({})
    validated = manager.validate({"action": "open_file", "target": str(tmp_path / "safe.txt")})
    assert validated.action == "open_file"


def test_security_validation_rejects_discovered_style_application_path():
    manager = ActionManager({"chrome": r"C:\\Program Files\\Google\\Chrome\\chrome.exe"})
    result = manager.execute({"action": "launch_application", "target": r"C:\\evil.exe"})
    assert result.success is False
    assert "approved" in (result.error or "").lower() or "application" in (result.error or "").lower()


def test_discovery_pipeline_resolves_file_then_uses_manager(tmp_path, monkeypatch):
    target = tmp_path / "notes.txt"
    target.write_text("x", encoding="utf-8")
    base = LLMCommandPipeline(FakeProvider(), apps={}, manager=ActionManager({}))
    discovery = DiscoveryManager({"search_roots": {"files": [str(tmp_path)], "folders": [str(tmp_path)]}, "timeout": 1}, {})
    manager = ActionManager({})
    calls = []
    monkeypatch.setattr(manager, "execute", lambda action: calls.append(action) or type("R", (), {"success": True, "message": "opened", "error": None})())
    pipeline = DiscoveryAwareCommandPipeline(base, discovery, manager)
    result = pipeline.handle("Open file notes")
    assert result.command.status is LLMStatus.ACTION
    assert calls == [{"action": "open_file", "target": str(target)}]


def test_ambiguous_pipeline_does_not_execute(tmp_path, monkeypatch):
    for name in ("project-a.txt", "project-b.txt"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    base = LLMCommandPipeline(FakeProvider(), apps={}, manager=ActionManager({}))
    discovery = DiscoveryManager({"search_roots": {"files": [str(tmp_path)]}, "max_results": 10, "timeout": 1}, {})
    manager = ActionManager({})
    calls = []
    monkeypatch.setattr(manager, "execute", lambda action: calls.append(action))
    result = DiscoveryAwareCommandPipeline(base, discovery, manager).handle("Open file project")
    assert result.command.status is LLMStatus.NEEDS_CLARIFICATION
    assert calls == []


def test_worker_background_execution_architecture():
    source = (Path(__file__).resolve().parent.parent / "gui" / "workers.py").read_text(encoding="utf-8")
    assert "self.command_pipeline.handle(self.text)" in source
    assert "self.speech_pipeline.listen_once()" in source


def test_gui_uses_discovery_aware_pipeline():
    source = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
    assert "DiscoveryManager" in source
    assert "DiscoveryAwareCommandPipeline" in source
    gui = (Path(__file__).resolve().parent.parent / "gui" / "main_window.py").read_text(encoding="utf-8")
    assert "command_pipeline" in gui


def test_discovery_has_no_execution_calls():
    root = Path(__file__).resolve().parent.parent / "discovery"
    source = "".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    forbidden = ("subprocess", "os.system", "Popen(", "PowerShell", "winsound", ".execute(", "ActionManager(")
    assert not any(token in source for token in forbidden)
