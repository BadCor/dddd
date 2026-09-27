"""Build user-facing text from existing Stage 4/2 results."""
from __future__ import annotations

from llm.pipeline import LLMRunResult


def response_text(result: LLMRunResult) -> str:
    """Return normal assistant text without exposing diagnostics or secrets."""
    if result.action_result is not None:
        action = result.action_result
        if action.success:
            detail = action.message or "The requested action completed successfully."
            return f"Done. {detail}"
        return action.error or "The requested action could not be completed."
    return result.command.message or "I could not process that request."
