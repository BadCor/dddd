"""
test_stage1.py

Verifies Stage 1 (project foundation):
    - Config loads defaults, creates a user config, merges overrides.
    - Config validation catches missing/invalid required keys.
    - Logging sets up a console + rotating file handler and actually writes.
    - main.bootstrap() handles a broken config without crashing (returns
      a clean StartupError instead of an unhandled traceback).

Run with:  pytest -v
"""

from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import ConfigManager, ConfigError  # noqa: E402
from core.logger import setup_logging  # noqa: E402


@pytest.fixture
def temp_project(tmp_path: Path) -> Path:
    """Create a throwaway copy of the project's config/ dir under tmp_path."""
    config_src = PROJECT_ROOT / "config" / "default_config.yaml"
    config_dst_dir = tmp_path / "config"
    config_dst_dir.mkdir()
    shutil.copy(config_src, config_dst_dir / "default_config.yaml")
    return tmp_path


# ----------------------------------------------------------------------
# ConfigManager
# ----------------------------------------------------------------------
class TestConfigManager:
    def test_loads_defaults_and_creates_user_config(self, temp_project: Path):
        cm = ConfigManager(temp_project)
        data = cm.load()

        assert data["app"]["name"] == "Voice Assistant"
        assert data["logging"]["level"] == "INFO"
        assert (temp_project / "config" / "config.yaml").exists()

    def test_user_overrides_are_merged_not_replaced(self, temp_project: Path):
        user_config_path = temp_project / "config" / "config.yaml"
        user_config_path.write_text(
            yaml.dump({"logging": {"level": "DEBUG"}}), encoding="utf-8"
        )

        cm = ConfigManager(temp_project)
        data = cm.load()

        # Override applied...
        assert data["logging"]["level"] == "DEBUG"
        # ...but sibling defaults preserved (proves deep merge, not overwrite).
        assert data["logging"]["log_file"] == "app.log"
        assert data["app"]["name"] == "Voice Assistant"

    def test_missing_default_config_raises_config_error(self, tmp_path: Path):
        empty_root = tmp_path / "empty"
        (empty_root / "config").mkdir(parents=True)

        cm = ConfigManager(empty_root)
        with pytest.raises(ConfigError):
            cm.load()

    def test_malformed_yaml_raises_config_error(self, temp_project: Path):
        user_config_path = temp_project / "config" / "config.yaml"
        user_config_path.write_text("logging: [unclosed", encoding="utf-8")

        cm = ConfigManager(temp_project)
        with pytest.raises(ConfigError):
            cm.load()

    def test_invalid_log_level_raises_config_error(self, temp_project: Path):
        user_config_path = temp_project / "config" / "config.yaml"
        user_config_path.write_text(
            yaml.dump({"logging": {"level": "NOT_A_LEVEL"}}), encoding="utf-8"
        )

        cm = ConfigManager(temp_project)
        with pytest.raises(ConfigError):
            cm.load()

    def test_get_helper_returns_default_for_missing_key(self, temp_project: Path):
        cm = ConfigManager(temp_project)
        cm.load()
        assert cm.get("nonexistent", "key", default="fallback") == "fallback"


# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------
class TestLogging:
    def test_creates_log_file_and_writes_to_it(self, tmp_path: Path):
        logging_config = {
            "level": "INFO",
            "log_dir": "logs",
            "log_file": "app.log",
            "max_bytes": 1_048_576,
            "backup_count": 3,
            "console_output": False,
        }
        logger = setup_logging(tmp_path, logging_config)
        logger.info("test message")
        for handler in logger.handlers:
            handler.flush()

        log_path = tmp_path / "logs" / "app.log"
        assert log_path.exists()
        assert "test message" in log_path.read_text(encoding="utf-8")

    def test_falls_back_gracefully_when_log_dir_unwritable(self, tmp_path: Path, monkeypatch):
        # Simulate an unwritable log directory by pointing log_dir at a
        # path that collides with an existing file (can't mkdir into a file).
        blocker = tmp_path / "logs_blocked"
        blocker.write_text("not a directory", encoding="utf-8")

        logging_config = {
            "level": "INFO",
            "log_dir": "logs_blocked",
            "log_file": "app.log",
            "console_output": True,
        }
        # Should not raise, should fall back to console-only logging.
        logger = setup_logging(tmp_path, logging_config)
        assert any(isinstance(h, logging.StreamHandler) for h in logger.handlers)

    def test_invalid_level_name_falls_back_to_info(self, tmp_path: Path):
        logging_config = {"level": "BOGUS", "console_output": True}
        logger = setup_logging(tmp_path, logging_config)
        assert logger.level == logging.INFO


# ----------------------------------------------------------------------
# main.py bootstrap / error handling
# ----------------------------------------------------------------------
class TestBootstrapErrorHandling:
    def test_bootstrap_raises_startup_error_on_bad_config(self, tmp_path, monkeypatch):
        import importlib
        import main as main_module

        monkeypatch.setattr(main_module, "PROJECT_ROOT", tmp_path)
        (tmp_path / "config").mkdir()
        # No default_config.yaml present -> ConfigError -> StartupError

        from core.exceptions import StartupError

        with pytest.raises(StartupError):
            main_module.bootstrap()

        importlib.reload(main_module)  # restore PROJECT_ROOT for other tests

    def test_main_returns_nonzero_on_startup_failure(self, tmp_path, monkeypatch):
        import importlib
        import main as main_module

        monkeypatch.setattr(main_module, "PROJECT_ROOT", tmp_path)
        (tmp_path / "config").mkdir()

        exit_code = main_module.main()
        assert exit_code == 1

        importlib.reload(main_module)
