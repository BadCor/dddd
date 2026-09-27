"""Stage 3 parser -> Stage 2 validation -> Stage 2 execution pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from actions.manager import ActionManager
from actions.result import ActionResult

from .parser import CommandParser
from .result import CommandResult, CommandStatus


@dataclass(frozen=True)
class PipelineResult:
    command: CommandResult
    action_result: ActionResult | None = None


class CommandPipeline:
    """Execute only actions produced by the parser through ActionManager."""

    def __init__(self, apps: Mapping[str, Any] | None = None, manager: ActionManager | None = None):
        self.parser = CommandParser(apps)
        self.manager = manager or ActionManager(apps)

    def handle(self, text: str) -> PipelineResult:
        parsed = self.parser.parse(text)
        if parsed.status is not CommandStatus.ACTION or parsed.action is None:
            return PipelineResult(parsed)
        result = self.manager.execute(parsed.action)
        return PipelineResult(parsed, result)
