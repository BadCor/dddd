"""Stage 8 discovery coordinator and safe integration with Stage 4."""
from __future__ import annotations

from typing import Any, Mapping

from core.errors import ErrorCategory, error_info

from .application_discovery import ApplicationDiscovery
from .file_discovery import FileDiscovery
from .folder_discovery import FolderDiscovery
from .models import DiscoveryKind, DiscoveryResult, DiscoveryStatus


class DiscoveryManager:
    """Find candidates only; never executes an action."""

    def __init__(self, config: Mapping[str, Any] | None = None,
                 approved_apps: Mapping[str, Any] | None = None) -> None:
        config = config or {}
        self.enabled = bool(config.get("enabled", True))
        self.approved_apps = approved_apps or {}
        roots = config.get("search_roots", {}) or {}
        file_roots = roots.get("files") or _default_user_roots()
        folder_roots = roots.get("folders") or file_roots
        max_depth = int(config.get("max_depth", 4))
        max_results = int(config.get("max_results", 20))
        timeout = float(config.get("timeout", 2.0))
        self.file_roots = tuple(_expand_roots(file_roots))
        self.folder_roots = tuple(_expand_roots(folder_roots))
        self.files = FileDiscovery(self.file_roots, max_depth=max_depth, max_results=max_results, timeout=timeout)
        self.folders = FolderDiscovery(self.folder_roots, max_depth=max_depth, max_results=max_results, timeout=timeout)
        app_cfg = config.get("applications", {}) or {}
        self.applications = ApplicationDiscovery(
            approved_apps=self.approved_apps,
            start_menu=bool(app_cfg.get("start_menu", True)),
            registry=bool(app_cfg.get("registry", True)),
            max_results=max_results,
            timeout=timeout,
        )

    @property
    def safe_path_roots(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.file_roots, *self.folder_roots)))

    def search(self, query: str, kind: DiscoveryKind, **kwargs: Any) -> DiscoveryResult:
        if not self.enabled:
            return DiscoveryResult(DiscoveryStatus.DISABLED, kind, query=str(query), message="Discovery is disabled.")
        try:
            if kind is DiscoveryKind.FILE:
                return self.files.search(query, **kwargs)
            if kind is DiscoveryKind.FOLDER:
                return self.folders.search(query, **kwargs)
            return self.applications.search(query, cancel_event=kwargs.get("cancel_event"))
        except Exception as exc:
            info = error_info(exc, category=ErrorCategory.DISCOVERY, user_message="Discovery failed safely.")
            return DiscoveryResult(DiscoveryStatus.ERROR, kind, query=str(query), message=info.user_message, error_info=info)

    def discover_request(self, text: str) -> list[DiscoveryResult]:
        """Search likely target types without performing interpretation or execution."""
        raw = str(text).strip()
        target = _target_phrase(raw)
        if not target:
            return []
        lowered = raw.casefold()
        if "file" in lowered:
            return [self.search(target, DiscoveryKind.FILE)]
        if "folder" in lowered or "directory" in lowered or "project" in lowered:
            return [self.search(_strip_folder_words(target), DiscoveryKind.FOLDER)]
        # For a generic "open X", discovery is deliberately parallel across types.
        return [
            self.search(target, DiscoveryKind.APPLICATION),
            self.search(target, DiscoveryKind.FOLDER),
            self.search(target, DiscoveryKind.FILE),
        ]



def _default_user_roots() -> list[str]:
    from pathlib import Path
    home = str(Path.home())
    return [f"{home}/Downloads", f"{home}/Documents", f"{home}/Desktop"]


def _expand_roots(values) -> list[str]:
    from pathlib import Path
    home = str(Path.home())
    expanded = []
    for value in values:
        if isinstance(value, (str, Path)):
            expanded.append(str(value).replace("{home}", home))
    return expanded


def _target_phrase(text: str) -> str:
    import re
    value = str(text).strip().strip('"\'')
    patterns = (
        r"^(?:please\s+|could\s+you\s+)?(?:open|find|locate|show)\s+(?:my\s+)?(?:the\s+)?(.+)$",
        r"^(?:please\s+|could\s+you\s+)?(?:launch|start|run)\s+(.+)$",
    )
    for pattern in patterns:
        match = re.match(pattern, value, re.IGNORECASE)
        if match:
            return match.group(1).strip().strip('"\'')
    return value


def _strip_folder_words(value: str) -> str:
    import re
    return re.sub(r"\s+(?:folder|directory)$", "", value, flags=re.IGNORECASE).strip()
