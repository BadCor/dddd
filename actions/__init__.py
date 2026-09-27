"""Stage 2 safe Windows action layer."""

from .manager import ActionManager
from .result import ActionResult
from .validators import SUPPORTED_ACTIONS, ValidatedAction, validate_action

__all__ = ["ActionManager", "ActionResult", "SUPPORTED_ACTIONS", "ValidatedAction", "validate_action"]
