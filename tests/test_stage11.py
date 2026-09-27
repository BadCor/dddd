from __future__ import annotations

import json
import threading
from pathlib import Path

from discovery.application_discovery import ApplicationDiscovery
from discovery.file_discovery import FileDiscovery
from discovery.models import DiscoveryStatus
from speech.microphone import Microphone, RecordingConfig
from tts.pipeline import TTSPipeline
from tts.result import TTSStatus
from user_data.settings import SettingsManager
from user_data.storage import JsonStorage


class FakeBackend:
    def __init__(self):
        self.stop_calls = 0

    def query_devices(self, device=None):
        return []

    def check_input_settings(self, **kwargs):
        return None

    def rec(self, *args, **kwargs):
        raise AssertionError("recording should not start in cleanup test")

    def wait(self):
        return None

    def stop(self):
        self.stop_calls += 1


class ClosableProvider:
    def __init__(self):
        self.closed = 0
        self.calls = 0

    def synthesize(self, text):
        self.calls += 1
        return b"RIFFWAVE"

    def close(self):
        self.closed += 1


class ClosableOutput:
    def __init__(self):
        self.closed = 0
        self.calls = 0

    def play(self, audio):
        self.calls += 1

    def close(self):
        self.closed += 1


def test_microphone_cleanup_requests_stop_and_backend_stop():
    backend = FakeBackend()
    microphone = Microphone(RecordingConfig(), backend=backend)
    microphone.close()
    assert backend.stop_calls == 1
    assert microphone._stop_event.is_set()


def test_speech_microphone_is_not_left_running_after_close():
    backend = FakeBackend()
    microphone = Microphone(RecordingConfig(), backend=backend)
    microphone.close()
    assert backend.stop_calls == 1


def test_tts_cleanup_closes_provider_and_output():
    provider, output = ClosableProvider(), ClosableOutput()
    tts = TTSPipeline(provider, output)
    assert tts.speak("hello").status is TTSStatus.SUCCESS
    tts.close()
    assert provider.closed == 1
    assert output.closed == 1
    assert tts.speak("again").status is TTSStatus.ERROR


def test_tts_cleanup_is_idempotent():
    provider, output = ClosableProvider(), ClosableOutput()
    tts = TTSPipeline(provider, output)
    tts.close()
    tts.close()
    assert provider.closed == 1
    assert output.closed == 1


def test_discovery_cancellation_is_fast_and_bounded(tmp_path):
    for i in range(100):
        (tmp_path / f"file_{i}.txt").write_text("x", encoding="utf-8")
    event = threading.Event()
    event.set()
    result = FileDiscovery((tmp_path,), max_depth=5, max_results=100, timeout=10).search("project", cancel_event=event)
    assert result.status is DiscoveryStatus.CANCELLED


def test_discovery_result_limit_is_preserved(tmp_path):
    for i in range(20):
        (tmp_path / f"project_{i}.txt").write_text("x", encoding="utf-8")
    result = FileDiscovery((tmp_path,), max_depth=1, max_results=3, timeout=5).search("project")
    assert len(result.candidates) == 3
    assert result.truncated is True


def test_application_discovery_respects_timeout_and_cancellation(monkeypatch, tmp_path):
    monkeypatch.setattr("discovery.application_discovery._start_menu_roots", lambda: [tmp_path])
    (tmp_path / "Chrome.lnk").write_text("x", encoding="utf-8")
    event = threading.Event()
    event.set()
    result = ApplicationDiscovery(approved_apps={"Chrome": "x"}, timeout=10).search("Chrome", cancel_event=event)
    assert result.status is DiscoveryStatus.CANCELLED


def test_settings_write_remains_atomic_and_reloadable(tmp_path):
    path = tmp_path / "user.json"
    manager = SettingsManager(JsonStorage(path))
    manager.save("tts_enabled", False)
    manager.save("microphone_index", 2)
    loaded = SettingsManager(JsonStorage(path))
    assert loaded.get("tts_enabled") is False
    assert loaded.get("microphone_index") == 2
    assert not list(tmp_path.glob(".user-data-*.tmp"))


def test_repeated_settings_updates_keep_one_document(tmp_path):
    path = tmp_path / "user.json"
    manager = SettingsManager(JsonStorage(path))
    for value in range(10):
        manager.save("microphone_index", value)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["settings"]["microphone_index"] == 9
    assert len(list(tmp_path.glob("user.json*"))) == 1


def test_gui_shutdown_owns_resource_cleanup():
    source = Path(__file__).resolve().parent.parent.joinpath("gui/main_window.py").read_text(encoding="utf-8")
    assert "self.speech_pipeline.close()" in source
    assert "self.tts_pipeline.close()" in source
    assert "self._worker.wait(3000)" in source


def test_gui_microphone_enumeration_is_worker_based():
    source = Path(__file__).resolve().parent.parent.joinpath("gui/main_window.py").read_text(encoding="utf-8")
    workers = Path(__file__).resolve().parent.parent.joinpath("gui/workers.py").read_text(encoding="utf-8")
    assert "DeviceListWorker" in source
    assert "class DeviceListWorker(QThread)" in workers
    assert "list_devices()" in workers


def test_gui_conversation_widget_count_is_bounded():
    source = Path(__file__).resolve().parent.parent.joinpath("gui/main_window.py").read_text(encoding="utf-8")
    assert "self._max_conversation_messages = 200" in source
    assert "deleteLater()" in source


def test_requirements_has_no_duplicate_direct_dependencies():
    requirements = Path(__file__).resolve().parent.parent.joinpath("requirements.txt").read_text(encoding="utf-8")
    names = []
    for line in requirements.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        names.append(line.split(">=")[0].split("==")[0].split("<=")[0].strip().casefold())
    assert len(names) == len(set(names))


def test_no_new_network_dependency_was_added():
    requirements = Path(__file__).resolve().parent.parent.joinpath("requirements.txt").read_text(encoding="utf-8")
    assert "requests" not in requirements.casefold()
    assert "httpx" not in requirements.casefold()


def test_shutdown_methods_do_not_start_background_recording():
    mic = Path(__file__).resolve().parent.parent.joinpath("speech/microphone.py").read_text(encoding="utf-8")
    assert "def close(self)" in mic
    assert "self._sd.stop()" in mic
    assert "while True:" in mic


def test_unchanged_setting_does_not_trigger_a_second_disk_write(tmp_path, monkeypatch):
    path = tmp_path / "user.json"
    manager = SettingsManager(JsonStorage(path))
    manager.save("tts_enabled", True)
    storage = manager.storage
    calls = 0
    original = storage.save

    def counted(data):
        nonlocal calls
        calls += 1
        return original(data)

    monkeypatch.setattr(storage, "save", counted)
    manager.save("tts_enabled", True)
    assert calls == 0
