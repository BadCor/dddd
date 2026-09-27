"""Structured, non-executing discovery results."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.errors import ErrorInfo


class DiscoveryKind(str, Enum):
    FILE = "file"
    FOLDER = "folder"
    APPLICATION = "application"


class DiscoveryStatus(str, Enum):
    SUCCESS = "success"
    AMBIGUOUS = "ambiguous"
    NO_RESULTS = "no_results"
    ERROR = "error"
    CANCELLED = "cancelled"
    DISABLED = "disabled"


@dataclass(frozen=True)
class FileCandidate:
    name: str
    path: str
    type: str = "file"
    size: int | None = None
    modified_time: float | None = None
    relevance: float = 0.0
    source: str = "configured_root"


@dataclass(frozen=True)
class FolderCandidate:
    name: str
    path: str
    type: str = "folder"
    modified_time: float | None = None
    relevance: float = 0.0
    source: str = "configured_root"


@dataclass(frozen=True)
class ApplicationCandidate:
    name: str
    shortcut_path: str | None = None
    executable_path: str | None = None
    source: str = "start_menu"
    relevance: float = 0.0
    approved: bool = False


@dataclass(frozen=True)
class DiscoveryResult:
    status: DiscoveryStatus
    kind: DiscoveryKind
    candidates: tuple[Any, ...] = field(default_factory=tuple)
    message: str = ""
    query: str = ""
    truncated: bool = False
    elapsed_seconds: float = 0.0
    error_info: ErrorInfo | None = None

    @property
    def is_single(self) -> bool:
        return self.status is DiscoveryStatus.SUCCESS and len(self.candidates) == 1

    @property
    def selected(self) -> Any | None:
        return self.candidates[0] if self.is_single else None
