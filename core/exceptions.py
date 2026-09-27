"""Shared application exception hierarchy."""


class AssistantError(Exception):
    """Base class for all expected/handled application errors."""


class StartupError(AssistantError):
    """Raised when the application cannot start."""


class ActionError(AssistantError):
    """Base class for expected action-layer failures."""


class ActionValidationError(ActionError):
    """Raised when an action request is malformed or unsafe."""


class ActionExecutionError(ActionError):
    """Raised when a validated action cannot be executed by the OS."""
