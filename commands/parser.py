"""Deterministic Stage 3 text-command parser.

The parser only translates text into Stage 2 action dictionaries. It never
executes Windows operations. This deliberately small rule-based interface can
be replaced by an LLM layer in a later stage without changing ActionManager.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from .result import CommandResult, CommandStatus


_OPEN_FILE_PATTERNS = (
    r"^(?:please\s+|could\s+you\s+)?open\s+(?:the\s+)?file\s+(.+)$",
    r"^(?:пожалуйста\s+)?открой\s+файл\s+(.+)$",
)
_OPEN_FOLDER_PATTERNS = (
    r"^(?:please\s+|could\s+you\s+)?open\s+(?:the\s+)?folder\s+(.+)$",
    r"^(?:please\s+|could\s+you\s+)?open\s+my\s+(.+?)\s+folder$",
    r"^(?:пожалуйста\s+)?открой\s+папку\s+(.+)$",
)
_LAUNCH_PATTERNS = (
    r"^(?:please\s+|could\s+you\s+)?(?:launch|start|run)\s+(.+)$",
    r"^(?:пожалуйста\s+)?(?:запусти|открой|стартуй)\s+(.+)$",
)
_OPEN_PATTERNS = (
    r"^(?:please\s+|could\s+you\s+)?open\s+(.+)$",
    r"^(?:пожалуйста\s+)?открой\s+(?:мне\s+)?(.+)$",
)

# Safe, conventional Windows user folders. These are semantic aliases, not
# arbitrary path discovery. The actual path is resolved without executing it.
_FOLDER_ALIASES = {
    "downloads": "Downloads",
    "download": "Downloads",
    "documents": "Documents",
    "document": "Documents",
    "desktop": "Desktop",
    "pictures": "Pictures",
    "picture": "Pictures",
    "photos": "Pictures",
    "music": "Music",
    "videos": "Videos",
    "video": "Videos",
    "загрузки": "Downloads",
    "загрузку": "Downloads",
    "документы": "Documents",
    "документы": "Documents",
    "рабочий стол": "Desktop",
    "изображения": "Pictures",
    "музыка": "Music",
    "видео": "Videos",
}


def _clean_target(value: str) -> str:
    return value.strip().strip('"').strip("'").strip(" \,!?.").strip()


def _normalize_command(value: str) -> str:
    """Make common polite Russian requests match the deterministic rules.

    Speech recognition often omits punctuation, while typed requests usually
    include it.  Keeping this normalization local means both inputs follow the
    same safe allowlist-based launch path.
    """
    value = value.strip()
    value = re.sub(r"[,:;!?.]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"^(?:эй\s+)?(?:ассистент\s+)?(?:можешь|сможешь|не\s+мог\s+бы\s+ты)\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^(?:пожалуйста\s+)?открыть\s+", lambda match: "пожалуйста открой " if match.group(0).casefold().startswith("пожалуйста") else "открой ", value, flags=re.IGNORECASE)
    value = re.sub(r"^(?:пожалуйста\s+)?запустить\s+", lambda match: "пожалуйста запусти " if match.group(0).casefold().startswith("пожалуйста") else "запусти ", value, flags=re.IGNORECASE)
    value = re.sub(r"^(открой|запусти|стартуй)\s+пожалуйста\s+", r"пожалуйста \1 ", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+пожалуйста$", "", value, flags=re.IGNORECASE)
    return value


def _action(action: str, target: str) -> CommandResult:
    return CommandResult(
        CommandStatus.ACTION,
        f"Understood as {action}: {target}",
        {"action": action, "target": target},
    )


def _match(patterns: tuple[str, ...], text: str) -> str | None:
    for pattern in patterns:
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if match:
            return _clean_target(match.group(1))
    return None


class CommandParser:
    """Parse simple text commands into safe, structured Stage 2 actions."""

    def __init__(self, apps: Mapping[str, Any] | None = None):
        self.apps = {str(name).casefold(): value for name, value in (apps or {}).items()}

    def parse(self, text: Any) -> CommandResult:
        if not isinstance(text, str):
            return CommandResult(CommandStatus.INVALID, "Command must be text.")

        command = _normalize_command(text)
        if not command:
            return CommandResult(CommandStatus.INVALID, "Command cannot be empty.")

        # A configured application name can also be used as a short code word,
        # e.g. "телеграм".  It is still limited to the explicit allowlist.
        if command.casefold() in self.apps:
            return _action("launch_application", command)

        # Explicit URL intent is checked before generic 'open'.
        target = _clean_target(command)
        if re.match(r"^(?:please\s+|could\s+you\s+)?open\s+", target, re.I) or re.match(r"^(?:пожалуйста\s+)?открой\s+", target, re.I):
            candidate = _match(_OPEN_PATTERNS, target)
            if candidate and self._looks_like_url(candidate):
                return _action("open_url", candidate)

        target = _match(_OPEN_FILE_PATTERNS, command)
        if target:
            return _action("open_file", target)

        target = _match(_OPEN_FOLDER_PATTERNS, command)
        if target:
            resolved = self._resolve_folder_alias(target)
            return _action("open_folder", resolved)

        target = _match(_LAUNCH_PATTERNS, command)
        if target:
            return self._parse_launch(target)

        target = _match(_OPEN_PATTERNS, command)
        if target:
            return self._parse_open(target)

        # Commands that begin like an actionable request but are incomplete
        # receive a distinct invalid result rather than an unsupported one.
        if re.match(r"^(?:please\s+|could\s+you\s+)?(?:open|launch|start|run)\s*$", command, re.I) or re.match(r"^(?:пожалуйста\s+)?(?:открой|запусти|стартуй)\s*$", command, re.I):
            return CommandResult(CommandStatus.INVALID, "Команда неполная. Укажите, что открыть или запустить.")

        return CommandResult(CommandStatus.UNSUPPORTED, "I don't understand that command yet.")

    def _parse_launch(self, target: str) -> CommandResult:
        key = target.casefold()
        if key in self.apps:
            return _action("launch_application", target)
        return CommandResult(CommandStatus.UNSUPPORTED, "That application is not approved or configured.")

    def _parse_open(self, target: str) -> CommandResult:
        if not target:
            return CommandResult(CommandStatus.INVALID, "The command is incomplete. Please specify what to open.")

        if self._looks_like_url(target):
            return _action("open_url", target)

        key = target.casefold()
        app_match = key in self.apps
        folder_path = self._resolve_folder_alias(target)
        folder_match = target.casefold() in _FOLDER_ALIASES or self._path_exists_as_dir(folder_path)
        file_match = self._path_exists_as_file(target)

        if app_match and folder_match:
            return CommandResult(
                CommandStatus.NEEDS_CLARIFICATION,
                f"Do you want to open the {target} application or the {target} folder?",
            )
        if app_match and file_match:
            return CommandResult(
                CommandStatus.NEEDS_CLARIFICATION,
                f"Do you want to open the {target} application or the {target} file?",
            )
        if app_match:
            return _action("launch_application", target)
        if folder_match:
            return _action("open_folder", folder_path)
        if file_match:
            return _action("open_file", target)

        # A path-looking target is allowed through to Stage 2 so that its
        # validation/action layer can return the precise safe failure.
        if self._looks_like_path(target):
            return _action("open_file", target)

        # Unknown simple names are ambiguous: the parser refuses to guess.
        return CommandResult(
            CommandStatus.NEEDS_CLARIFICATION,
            f"Do you want to open the {target} application or the {target} folder?",
        )

    @staticmethod
    def _looks_like_url(value: str) -> bool:
        try:
            parsed = urlparse(value)
        except ValueError:
            return False
        return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)

    @staticmethod
    def _looks_like_path(value: str) -> bool:
        return (
            "\\" in value
            or "/" in value
            or value.startswith((".", "~"))
            or bool(re.match(r"^[A-Za-z]:", value))
        )

    @staticmethod
    def _resolve_folder_alias(value: str) -> str:
        alias = _FOLDER_ALIASES.get(value.casefold())
        if not alias:
            return value
        return str(Path.home() / alias)

    @staticmethod
    def _path_exists_as_dir(value: str) -> bool:
        try:
            return Path(value).is_dir()
        except (OSError, ValueError):
            return False

    @staticmethod
    def _path_exists_as_file(value: str) -> bool:
        try:
            return Path(value).is_file()
        except (OSError, ValueError):
            return False
