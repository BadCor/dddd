"""Validated persistent application settings."""
from __future__ import annotations


from typing import Any, Mapping

from .storage import JsonStorage, StorageError

_ALLOWED_PROVIDERS = {"none", "openai", "openai_compatible"}
_SECRET_KEYS = {"api_key", "api_key_env_var", "password", "token", "secret", "credential"}


def _reject_secret_key(key: str) -> None:
    lowered = key.casefold()
    if lowered in _SECRET_KEYS or any(part in lowered for part in ("password", "token", "secret", "credential")):
        raise ValueError("Secrets and credentials cannot be persisted as user settings.")


class SettingsManager:
    """Persists only the explicitly supported, non-secret runtime settings."""

    def __init__(self, storage: JsonStorage):
        self.storage = storage
        self._settings = self._load_safe()

    def _load_safe(self) -> dict[str, Any]:
        try:
            data = self.storage.load()
        except StorageError:
            data = {"version": 1, "settings": {}, "memory": {}}
            try:
                self.storage.save(data)
            except StorageError:
                pass
        except Exception:
            data = {"version": 1, "settings": {}, "memory": {}}
        raw = data.get("settings", {})
        if not isinstance(raw, dict):
            return {}
        safe: dict[str, Any] = {}
        for key, value in raw.items():
            try:
                safe[key] = self._validate(key, value)
            except ValueError:
                continue
        return safe

    @staticmethod
    def _validate(key: str, value: Any) -> Any:
        _reject_secret_key(key)
        if key == "tts_enabled":
            if not isinstance(value, bool):
                raise ValueError("tts_enabled must be boolean")
            return value
        if key == "tts_voice":
            if value is not None and (not isinstance(value, str) or len(value) > 300):
                raise ValueError("tts_voice is invalid")
            return value
        if key == "tts_rate":
            value = int(value)
            if not 50 <= value <= 400:
                raise ValueError("tts_rate is out of range")
            return value
        if key == "tts_volume":
            value = float(value)
            if not 0.0 <= value <= 1.0:
                raise ValueError("tts_volume is out of range")
            return value
        if key == "microphone_index":
            if value is not None:
                value = int(value)
                if value < 0:
                    raise ValueError("microphone_index is invalid")
            return value
        if key == "llm_provider":
            if value not in _ALLOWED_PROVIDERS:
                raise ValueError("Unsupported LLM provider")
            return value
        if key == "llm_model":
            if not isinstance(value, str) or not value.strip() or len(value) > 200:
                raise ValueError("llm_model is invalid")
            return value.strip()
        raise ValueError("Unsupported setting")

    def get(self, key: str, default: Any = None) -> Any:
        return self._settings.get(key, default)

    def all(self) -> dict[str, Any]:
        return dict(self._settings)

    def save(self, key: str, value: Any) -> None:
        safe = self._validate(key, value)
        if self._settings.get(key) == safe:
            return
        self._settings[key] = safe
        self._persist()

    def update(self, values: Mapping[str, Any]) -> None:
        candidate = dict(self._settings)
        for key, value in values.items():
            candidate[key] = self._validate(key, value)
        self._settings = candidate
        self._persist()

    def clear(self) -> None:
        if not self._settings:
            return
        self._settings.clear()
        self._persist()

    def apply_to_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Apply saved settings to a runtime config copy; never writes YAML."""
        result = dict(config)
        tts = dict(result.get("tts", {}) or {})
        speech = dict(result.get("speech", {}) or {})
        llm = dict(result.get("llm", {}) or {})
        for key, target in (("tts_enabled", (tts, "enabled")), ("tts_voice", (tts, "voice")),
                            ("tts_rate", (tts, "rate")), ("tts_volume", (tts, "volume")),
                            ("microphone_index", (speech, "microphone_index")),
                            ("llm_provider", (llm, "provider")), ("llm_model", (llm, "model"))):
            if key in self._settings:
                target[0][target[1]] = self._settings[key]
        result["tts"], result["speech"], result["llm"] = tts, speech, llm
        return result

    def _persist(self) -> None:
        data = self.storage.load()
        data["version"] = 1
        data["settings"] = dict(self._settings)
        data.setdefault("memory", {})
        self.storage.save(data)
