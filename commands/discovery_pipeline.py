"""Stage 8 orchestration: existing interpretation -> discovery -> ActionManager."""
from __future__ import annotations

from typing import Any

from actions.manager import ActionManager
from llm.pipeline import LLMCommandPipeline, LLMRunResult
from llm.result import LLMCommandResult, LLMStatus
from discovery.manager import DiscoveryManager
from discovery.models import FileCandidate, FolderCandidate, ApplicationCandidate


class DiscoveryAwareCommandPipeline:
    """Adds candidate discovery without adding a second command parser."""

    def __init__(self, command_pipeline: LLMCommandPipeline, discovery: DiscoveryManager,
                 manager: ActionManager) -> None:
        self.command_pipeline = command_pipeline
        self.discovery = discovery
        self.manager = manager
        self.apps = getattr(command_pipeline, "apps", {})

    def handle(self, text: str) -> LLMRunResult:
        base = self.command_pipeline.handle(text)
        if base.action_result is not None or base.command.status is LLMStatus.ACTION:
            return base
        results = self.discovery.discover_request(text)
        candidates = _unique_candidates(results)
        if not candidates:
            return base
        if len(candidates) > 1:
            names = ", ".join(_candidate_label(item) for item in candidates[:6])
            command = LLMCommandResult(LLMStatus.NEEDS_CLARIFICATION,
                f"I found multiple possible targets: {names}. Please specify which one you mean.")
            return LLMRunResult(command, used_fallback=base.used_fallback)

        candidate = candidates[0]
        action = _candidate_action(candidate, self.command_pipeline.apps)
        if action is None:
            command = LLMCommandResult(LLMStatus.NEEDS_CLARIFICATION,
                "I found a candidate, but it is not approved for opening. Please add it to the approved applications or specify a file/folder path.")
            return LLMRunResult(command, used_fallback=base.used_fallback)

        # Discovery supplied only the candidate. The existing Stage 2 manager
        # performs validation and is the only execution layer.
        action_result = self.manager.execute(action)
        command = LLMCommandResult(LLMStatus.ACTION,
            f"Resolved the request to {action['target']}.", action)
        return LLMRunResult(command, action_result, used_fallback=base.used_fallback)


def _unique_candidates(results: list[Any]) -> list[Any]:
    candidates = []
    seen = set()
    for result in results:
        for candidate in result.candidates:
            key = (type(candidate).__name__, getattr(candidate, "path", None),
                   getattr(candidate, "shortcut_path", None), candidate.name.casefold())
            if key not in seen:
                seen.add(key)
                candidates.append(candidate)
    candidates.sort(key=lambda c: -getattr(c, "relevance", 0.0))
    return candidates


def _candidate_label(candidate: Any) -> str:
    path = getattr(candidate, "path", None) or getattr(candidate, "shortcut_path", None)
    return f"{candidate.name} ({path})" if path else candidate.name


def _candidate_action(candidate: Any, approved_apps) -> dict[str, str] | None:
    if isinstance(candidate, FileCandidate):
        return {"action": "open_file", "target": candidate.path}
    if isinstance(candidate, FolderCandidate):
        return {"action": "open_folder", "target": candidate.path}
    if isinstance(candidate, ApplicationCandidate):
        if candidate.name.casefold() not in {str(k).casefold() for k in approved_apps}:
            return None
        return {"action": "launch_application", "target": candidate.name}
    return None
