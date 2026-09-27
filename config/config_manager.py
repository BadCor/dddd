"""
config_manager.py

Loads application configuration from a bundled default file and an
optional user-editable override file, merges them, and validates the
result. Nothing else in the app should read YAML/JSON directly -
everything goes through ConfigManager so config handling stays in one
place as the project grows.
"""

from __future__ import annotations

import copy
import shutil
from pathlib import Path
from typing import Any, Dict

import yaml

from core.runtime_paths import bundled_root, is_frozen, user_data_root


class ConfigError(Exception):
    """Raised when configuration cannot be loaded or is invalid."""


# Keys that MUST exist (after merging defaults + user config) for the
# app to be considered safely configured. Extend this as new stages
# add required settings.
_REQUIRED_KEYS = [
    ("app", "name"),
    ("logging", "level"),
    ("logging", "log_dir"),
    ("logging", "log_file"),
]

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class ConfigManager:
    """Loads, merges, validates, and exposes application configuration."""

    def __init__(self, project_root: Path, user_config_name: str = "config.yaml"):
        self.project_root = Path(project_root)
        self.default_config_path = (bundled_root() if is_frozen() else self.project_root) / "config" / "default_config.yaml"
        if is_frozen():
            self.user_config_path = user_data_root() / "config" / user_config_name
        else:
            self.user_config_path = self.project_root / "config" / user_config_name
        self.apps_config_path = self.user_config_path.with_name("apps.yaml")
        self.apps_template_path = (bundled_root() if is_frozen() else self.project_root) / "config" / "apps.yaml"
        self._data: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def load(self) -> Dict[str, Any]:
        """Load defaults, create a user config if missing, merge, validate."""
        defaults = self._load_yaml_file(self.default_config_path, required=True)

        if not self.user_config_path.exists():
            # First run: give the user their own editable copy.
            try:
                shutil.copy(self.default_config_path, self.user_config_path)
            except OSError as exc:
                raise ConfigError(
                    f"Could not create user config at '{self.user_config_path}': {exc}"
                ) from exc

        user_overrides = self._load_yaml_file(self.user_config_path, required=False)

        merged = self._deep_merge(defaults, user_overrides)
        self._load_application_aliases(merged)
        self._validate(merged)
        self._data = merged
        return self._data

    def _load_yaml_file(self, path: Path, *, required: bool) -> Dict[str, Any]:
        if not path.exists():
            if required:
                raise ConfigError(f"Required configuration file not found: '{path}'")
            return {}

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"Malformed YAML in '{path}': {exc}") from exc
        except OSError as exc:
            raise ConfigError(f"Could not read '{path}': {exc}") from exc

        if not isinstance(data, dict):
            raise ConfigError(f"Config file '{path}' must contain a mapping at the top level.")

        return data

    def _load_application_aliases(self, config: Dict[str, Any]) -> None:
        """Load user-managed application code words from ``apps.yaml``."""
        if not self.apps_config_path.exists() and is_frozen():
            try:
                self.apps_config_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(self.apps_template_path, self.apps_config_path)
            except OSError as exc:
                raise ConfigError(
                    f"Could not create application aliases at '{self.apps_config_path}': {exc}"
                ) from exc

        aliases_data = self._load_yaml_file(self.apps_config_path, required=False)
        aliases = aliases_data.get("apps", aliases_data)
        if not isinstance(aliases, dict):
            raise ConfigError(f"Application aliases in '{self.apps_config_path}' must be a mapping.")
        config["apps"] = self._deep_merge(config.get("apps", {}) or {}, aliases)

    # ------------------------------------------------------------------
    # Merging
    # ------------------------------------------------------------------
    @staticmethod
    def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively merge override into a copy of base."""
        result = copy.deepcopy(base)
        for key, value in override.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = ConfigManager._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    @staticmethod
    def _validate(data: Dict[str, Any]) -> None:
        for path in _REQUIRED_KEYS:
            node = data
            for part in path:
                if not isinstance(node, dict) or part not in node:
                    raise ConfigError(
                        f"Missing required config key: '{'.'.join(path)}'"
                    )
                node = node[part]

        level = data.get("logging", {}).get("level")
        if level not in _VALID_LOG_LEVELS:
            raise ConfigError(
                f"Invalid logging.level '{level}'. Must be one of {sorted(_VALID_LOG_LEVELS)}."
            )

    # ------------------------------------------------------------------
    # Access helpers
    # ------------------------------------------------------------------
    def get(self, *keys: str, default: Any = None) -> Any:
        """Safely fetch a nested value, e.g. config.get('logging', 'level')."""
        node: Any = self._data
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    @property
    def data(self) -> Dict[str, Any]:
        return self._data
