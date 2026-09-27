"""Stage 4 LLM -> strict validation -> Stage 2 ActionManager pipeline."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping

from actions.manager import ActionManager
from actions.result import ActionResult
from core.errors import ErrorCategory, error_info
from commands.parser import CommandParser
from commands.result import CommandStatus

from .provider import LLMProvider
from .result import LLMCommandResult, LLMError, LLMStatus
from .validator import validate_llm_response

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMRunResult:
    command: LLMCommandResult
    action_result: ActionResult | None = None
    used_fallback: bool = False


class LLMCommandPipeline:
    def __init__(self, provider: LLMProvider | None, apps: Mapping[str, Any] | None = None,
                 manager: ActionManager | None = None, fallback_parser: CommandParser | None = None,
                 allowed_path_roots: tuple[str, ...] | list[str] | None = None):
        self.provider = provider
        self.apps = apps or {}
        self.manager = manager or ActionManager(self.apps)
        self.fallback_parser = fallback_parser or CommandParser(self.apps)
        self.allowed_path_roots = tuple(allowed_path_roots) if allowed_path_roots is not None else None

    def handle(self, text: str) -> LLMRunResult:
        if self.provider is None:
            return self._fallback(text, "LLM provider is not configured; using deterministic parser.")
        try:
            raw = self.provider.generate_command(text, approved_apps=self.apps)
            command = validate_llm_response(raw, approved_apps=self.apps, allowed_path_roots=self.allowed_path_roots)
        except LLMError as exc:
            info = error_info(exc, category=ErrorCategory.NETWORK, user_message="LLM processing failed safely.")
            logger.warning("LLM processing failed: %s", info.diagnostic)
            return self._fallback(text, info.user_message)
        except Exception as exc:
            info = error_info(exc, category=ErrorCategory.INTERNAL, user_message="LLM processing failed safely.")
            logger.error("Unexpected LLM processing failure: %s", info.diagnostic)
            return self._fallback(text, info.user_message)

        if command.status is not LLMStatus.ACTION or command.action is None:
            return LLMRunResult(command)

        # Stage 2 remains the only execution path.
        result = self.manager.execute(command.action)
        return LLMRunResult(command, result)

    def _fallback(self, text: str, reason: str) -> LLMRunResult:
        parsed = self.fallback_parser.parse(text)
        if parsed.status is CommandStatus.ACTION and parsed.action is not None:
            result = self.manager.execute(parsed.action)
            command = LLMCommandResult(LLMStatus.ACTION, parsed.message, parsed.action)
            return LLMRunResult(command, result, used_fallback=True)
        status_map = {
            CommandStatus.NEEDS_CLARIFICATION: LLMStatus.NEEDS_CLARIFICATION,
            CommandStatus.UNSUPPORTED: LLMStatus.UNSUPPORTED,
            CommandStatus.INVALID: LLMStatus.INVALID,
        }
        command = LLMCommandResult(status_map[parsed.status], parsed.message)
        logger.info("Deterministic fallback used: %s", reason)
        return LLMRunResult(command, used_fallback=True)
