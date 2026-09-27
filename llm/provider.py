"""Provider abstraction and an OpenAI-compatible HTTP implementation."""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from urllib.parse import urlparse
from dataclasses import dataclass
from typing import Any, Mapping

from .prompt import SYSTEM_PROMPT
from .result import LLMConfigurationError, LLMProviderError, LLMTimeoutError

logger = logging.getLogger(__name__)


def _validate_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme.lower() not in {"https", "http"} or not parsed.netloc:
        raise LLMConfigurationError("LLM endpoint must be a valid HTTP(S) URL.")
    if parsed.username is not None or parsed.password is not None:
        raise LLMConfigurationError("LLM endpoint may not contain embedded credentials.")
    if parsed.scheme.lower() == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise LLMConfigurationError("Non-local LLM endpoints must use HTTPS.")
    return endpoint


class LLMProvider:
    """Interface implemented by every Stage 4 model provider."""

    def generate_command(self, text: str, *, approved_apps: Mapping[str, Any]) -> str:
        raise NotImplementedError


@dataclass(frozen=True)
class OpenAICompatibleProvider(LLMProvider):
    """Small dependency-free client for OpenAI-compatible chat endpoints."""

    model: str
    endpoint: str
    api_key_env_var: str
    timeout: float = 20.0
    max_response_size: int = 8192

    def generate_command(self, text: str, *, approved_apps: Mapping[str, Any]) -> str:
        api_key = os.getenv(self.api_key_env_var)
        if not api_key:
            raise LLMConfigurationError("LLM API key is not configured.")

        app_names = sorted(str(name) for name in approved_apps)
        system = SYSTEM_PROMPT + "\n\nApproved application names:\n" + "\n".join(app_names)
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "status": {"type": "string", "enum": ["action", "needs_clarification", "unsupported", "invalid"]},
                "action": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "action": {"type": "string", "enum": ["open_file", "open_folder", "open_url", "launch_application"]},
                        "target": {"type": "string"},
                    },
                    "required": ["action", "target"],
                },
                "message": {"type": "string"},
            },
            "required": ["status", "message"],
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
            "temperature": 0,
            "response_format": {"type": "json_schema", "json_schema": {"name": "assistant_command", "strict": True, "schema": schema}},
            "max_tokens": 512,
        }
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read(self.max_response_size + 1)
        except TimeoutError as exc:
            raise LLMTimeoutError("LLM request timed out.") from exc
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise LLMProviderError("LLM provider rate limit reached.") from exc
            if exc.code in {401, 403}:
                raise LLMProviderError("LLM provider authentication failed.") from exc
            raise LLMProviderError("LLM provider request failed.") from exc
        except urllib.error.URLError as exc:
            raise LLMProviderError("LLM provider is unavailable.") from exc
        except OSError as exc:
            raise LLMProviderError("LLM provider request failed.") from exc

        if len(raw) > self.max_response_size:
            raise LLMProviderError("LLM response exceeded the configured size limit.")
        try:
            envelope = json.loads(raw.decode("utf-8"))
            content = envelope["choices"][0]["message"]["content"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError("LLM provider returned an invalid response envelope.") from exc
        if not isinstance(content, str):
            raise LLMProviderError("LLM provider returned non-text command data.")
        return content


def build_provider(config: Mapping[str, Any]) -> LLMProvider | None:
    provider = str(config.get("provider", "none")).strip().lower()
    if provider in {"none", ""}:
        return None
    if provider in {"openai", "openai_compatible"}:
        endpoint = _validate_endpoint(str(config.get("endpoint", "https://api.openai.com/v1/chat/completions")))
        timeout = float(config.get("timeout", 20))
        max_response_size = int(config.get("max_response_size", 8192))
        if not 0.1 <= timeout <= 120:
            raise LLMConfigurationError("LLM timeout is outside the safe range.")
        if not 256 <= max_response_size <= 1_048_576:
            raise LLMConfigurationError("LLM response size limit is outside the safe range.")
        return OpenAICompatibleProvider(
            model=str(config.get("model", "gpt-5.6-luna")),
            endpoint=endpoint,
            api_key_env_var=str(config.get("api_key_env_var", "ASSISTANT_LLM_API_KEY")),
            timeout=timeout,
            max_response_size=max_response_size,
        )
    raise LLMConfigurationError(f"Unsupported LLM provider: '{provider}'.")
