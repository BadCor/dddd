"""Stage 9 explicit-memory adapter over the existing command pipeline."""
from __future__ import annotations

from user_data.memory import MemoryManager, parse_explicit_memory_request
from user_data.models import MemoryCategory, MemoryOperation, MemoryOperationType
from llm.result import LLMCommandResult, LLMStatus
from llm.pipeline import LLMRunResult


class MemoryAwareCommandPipeline:
    """Handles only explicit memory operations, then delegates everything else."""

    def __init__(self, command_pipeline, memory_manager: MemoryManager):
        self.command_pipeline = command_pipeline
        self.memory_manager = memory_manager
        self.apps = getattr(command_pipeline, "apps", {})

    def handle(self, text: str) -> LLMRunResult:
        base = self.command_pipeline.handle(text)
        if base.command.status is LLMStatus.MEMORY and base.command.memory is not None:
            result = self._apply_dict(base.command.memory)
            return LLMRunResult(
                LLMCommandResult(
                    LLMStatus.ACTION if result.success else LLMStatus.INVALID,
                    result.message,
                    memory=base.command.memory,
                ),
                used_fallback=base.used_fallback,
            )
        if base.action_result is not None or base.command.status is LLMStatus.ACTION:
            return base

        operation = parse_explicit_memory_request(text, self.apps)
        if operation is None:
            return base
        result = self.memory_manager.apply(operation)
        status = LLMStatus.ACTION if result.success else LLMStatus.INVALID
        return LLMRunResult(
            LLMCommandResult(status, result.message, memory={
                "operation": operation.operation.value,
                "category": operation.category.value if operation.category else "",
                "key": operation.key or "default",
                "value": operation.value or "",
            }),
            used_fallback=base.used_fallback,
        )

    def _apply_dict(self, data: dict[str, str]):
        category = MemoryCategory(data["category"])
        operation = MemoryOperation(
            MemoryOperationType(data["operation"]),
            category,
            data.get("key") or "default",
            data.get("value") or None,
        )
        return self.memory_manager.apply(operation)
