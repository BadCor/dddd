"""Comprehensive Stage 2 action-layer tests.

All OS/browser boundaries are mocked: these tests never launch applications,
open Explorer, or navigate a real browser.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from actions import ActionManager, validate_action  # noqa: E402
from actions import app_actions, file_actions, url_actions  # noqa: E402
from core.exceptions import ActionValidationError  # noqa: E402


@pytest.fixture
def manager(tmp_path: Path) -> ActionManager:
    approved = tmp_path / "approved.exe"
    approved.write_bytes(b"test")
    return ActionManager({"testapp": str(approved)})


class TestValidation:
    @pytest.mark.parametrize("action", ["open_file", "open_folder", "open_url", "launch_application"])
    def test_supported_actions_validate(self, action, tmp_path):
        target = "https://example.com" if action == "open_url" else str(tmp_path / "x")
        result = validate_action({"action": action, "target": target})
        assert result.action == action
        assert result.target == target

    def test_unknown_action_rejected(self):
        with pytest.raises(ActionValidationError, match="Unknown action"):
            validate_action({"action": "run_command", "target": "dir"})

    @pytest.mark.parametrize("raw", [None, [], "open_file", 123])
    def test_malformed_action_rejected(self, raw):
        with pytest.raises(ActionValidationError):
            validate_action(raw)

    def test_missing_action_rejected(self):
        with pytest.raises(ActionValidationError, match="Action name"):
            validate_action({"target": "x"})

    def test_missing_target_rejected(self):
        with pytest.raises(ActionValidationError, match="target"):
            validate_action({"action": "open_file"})

    @pytest.mark.parametrize("target", [None, 123, [], "", "   ", "abc\x00def"])
    def test_invalid_target_types_rejected(self, target):
        with pytest.raises(ActionValidationError):
            validate_action({"action": "open_file", "target": target})

    def test_unexpected_parameters_rejected(self):
        with pytest.raises(ActionValidationError, match="Unsupported action parameters"):
            validate_action({"action": "open_file", "target": "x", "command": "dir"})

    @pytest.mark.parametrize("url", [
        "file:///C:/secret.txt",
        "javascript:alert(1)",
        "data:text/plain,hello",
        "vbscript:msgbox(1)",
        "ftp://example.com/file",
        "example.com",
        "https:///missing-host",
    ])
    def test_invalid_url_schemes_or_shape_rejected(self, url):
        with pytest.raises(ActionValidationError):
            validate_action({"action": "open_url", "target": url})

    @pytest.mark.parametrize("url", ["http://example.com", "https://example.com/path?q=1"])
    def test_http_and_https_accepted(self, url):
        assert validate_action({"action": "open_url", "target": url}).target == url


class TestFileAndFolderActions:
    def test_existing_file(self, tmp_path, monkeypatch):
        path = tmp_path / "hello.txt"
        path.write_text("hello", encoding="utf-8")
        opened = []
        monkeypatch.setattr(file_actions.windows, "open_path", lambda p: opened.append(p))

        result = file_actions.open_file(str(path))
        assert result.to_dict() == {
            "success": True,
            "action": "open_file",
            "message": "File opened successfully.",
            "error": None,
        }
        assert opened == [path]

    def test_nonexistent_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(file_actions.windows, "open_path", lambda _: pytest.fail("must not open"))
        result = file_actions.open_file(str(tmp_path / "missing.txt"))
        assert result.success is False
        assert result.error == "File does not exist."

    def test_directory_passed_as_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(file_actions.windows, "open_path", lambda _: pytest.fail("must not open"))
        result = file_actions.open_file(str(tmp_path))
        assert result.error == "Path is not a file."

    def test_existing_directory(self, tmp_path, monkeypatch):
        opened = []
        monkeypatch.setattr(file_actions.windows, "open_path", lambda p: opened.append(p))
        result = file_actions.open_folder(str(tmp_path))
        assert result.success is True
        assert result.action == "open_folder"
        assert opened == [tmp_path]

    def test_nonexistent_directory(self, tmp_path, monkeypatch):
        monkeypatch.setattr(file_actions.windows, "open_path", lambda _: pytest.fail("must not open"))
        result = file_actions.open_folder(str(tmp_path / "missing"))
        assert result.error == "Folder does not exist."

    def test_file_passed_as_directory(self, tmp_path, monkeypatch):
        path = tmp_path / "file.txt"
        path.write_text("x", encoding="utf-8")
        monkeypatch.setattr(file_actions.windows, "open_path", lambda _: pytest.fail("must not open"))
        result = file_actions.open_folder(str(path))
        assert result.error == "Path is not a folder."

    def test_invalid_path_is_clean_failure(self, monkeypatch):
        result = file_actions.open_file("\x00bad")
        assert result.success is False
        assert result.error is not None

    def test_permission_failure(self, tmp_path, monkeypatch):
        path = tmp_path / "secret.txt"
        path.write_text("x", encoding="utf-8")
        monkeypatch.setattr(file_actions.windows, "open_path", lambda _: (_ for _ in ()).throw(PermissionError()))
        result = file_actions.open_file(str(path))
        assert result.error == "Permission denied."

    def test_os_failure(self, tmp_path, monkeypatch):
        path = tmp_path / "broken.txt"
        path.write_text("x", encoding="utf-8")
        monkeypatch.setattr(file_actions.windows, "open_path", lambda _: (_ for _ in ()).throw(OSError("boom")))
        result = file_actions.open_file(str(path))
        assert result.error == "Could not open file."


class TestUrlAction:
    def test_http_url(self, monkeypatch):
        opened = []
        monkeypatch.setattr(url_actions.windows, "open_browser_url", lambda url: opened.append(url))
        result = url_actions.open_url("http://example.com")
        assert result.success is True
        assert opened == ["http://example.com"]

    def test_https_url(self, monkeypatch):
        opened = []
        monkeypatch.setattr(url_actions.windows, "open_browser_url", lambda url: opened.append(url))
        result = url_actions.open_url("https://example.com")
        assert result.success is True
        assert opened == ["https://example.com"]

    @pytest.mark.parametrize("url", ["file:///x", "javascript:alert(1)", "data:text/plain,x", "vbscript:x"])
    def test_rejected_url_never_reaches_browser(self, url, monkeypatch):
        monkeypatch.setattr(url_actions.windows, "open_browser_url", lambda _: pytest.fail("must not open"))
        result = url_actions.open_url(url)
        assert result.success is False

    def test_browser_os_failure(self, monkeypatch):
        monkeypatch.setattr(url_actions.windows, "open_browser_url", lambda _: (_ for _ in ()).throw(OSError("boom")))
        result = url_actions.open_url("https://example.com")
        assert result.error == "Could not open URL."


class TestApplications:
    def test_approved_application(self, manager, monkeypatch):
        opened = []
        monkeypatch.setattr(app_actions.windows, "launch_configured_application", lambda p: opened.append(p))
        result = manager.execute({"action": "launch_application", "target": "testapp"})
        assert result.success is True
        assert opened and opened[0].name == "approved.exe"

    def test_unapproved_application(self, manager, monkeypatch):
        monkeypatch.setattr(app_actions.windows, "launch_configured_application", lambda _: pytest.fail("must not launch"))
        result = manager.execute({"action": "launch_application", "target": "powershell"})
        assert result.success is False
        assert result.error == "Application is not approved/configured."

    def test_configured_missing_application(self, tmp_path, monkeypatch):
        manager = ActionManager({"broken": str(tmp_path / "missing.exe")})
        monkeypatch.setattr(app_actions.windows, "launch_configured_application", lambda _: pytest.fail("must not launch"))
        result = manager.execute({"action": "launch_application", "target": "broken"})
        assert result.error == "Configured application does not exist."

    def test_caller_cannot_supply_arbitrary_executable_path(self, manager, monkeypatch):
        arbitrary = str(tmp_path := Path.cwd() / "not-approved.exe")
        monkeypatch.setattr(app_actions.windows, "launch_configured_application", lambda _: pytest.fail("must not launch"))
        result = manager.execute({"action": "launch_application", "target": arbitrary})
        assert result.success is False
        assert result.error == "Application is not approved/configured."


class TestActionManager:
    def test_unknown_action_returns_structured_failure(self, manager):
        result = manager.execute({"action": "unknown", "target": "x"})
        assert result.to_dict()["success"] is False
        assert result.action == "unknown"

    def test_missing_parameter_returns_structured_failure(self, manager):
        result = manager.execute({"action": "open_folder"})
        assert result.success is False
        assert result.action == "open_folder"
        assert result.error

    def test_malformed_action_returns_structured_failure(self, manager):
        result = manager.execute(None)
        assert result.success is False
        assert result.action == "unknown"

    def test_validated_dispatch(self, manager, tmp_path, monkeypatch):
        monkeypatch.setattr(file_actions.windows, "open_path", lambda _: None)
        validated = manager.validate({"action": "open_folder", "target": str(tmp_path)})
        result = manager.execute_validated(validated)
        assert result.success is True

    def test_execute_validated_rejects_unvalidated_data(self, manager):
        result = manager.execute_validated({"action": "open_folder", "target": "."})
        assert result.success is False


class TestCleanApplication:
    def test_bootstrap_and_status_components_work(self, tmp_path):
        from config import ConfigManager
        from core.logger import setup_logging

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        source = PROJECT_ROOT / "config" / "default_config.yaml"
        (config_dir / "default_config.yaml").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        cm = ConfigManager(tmp_path)
        data = cm.load()
        logger = setup_logging(tmp_path, data["logging"])
        assert data["apps"] == {}
        logger.info("clean stage2 test run")
        assert (tmp_path / "logs" / "app.log").exists()
