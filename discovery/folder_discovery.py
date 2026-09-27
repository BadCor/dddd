"""Safe folder discovery inside explicitly configured roots."""
from __future__ import annotations

import os
import time
from pathlib import Path
from threading import Event
from typing import Iterable

from .file_discovery import _normalize_query, _safe_search_root, _score
from .models import DiscoveryKind, DiscoveryResult, DiscoveryStatus, FolderCandidate


class FolderDiscovery:
    def __init__(self, roots: Iterable[str | Path], *, max_depth: int = 4,
                 max_results: int = 20, timeout: float = 2.0) -> None:
        self.roots = tuple(Path(r).expanduser() for r in roots)
        self.max_depth = max(0, int(max_depth))
        self.max_results = max(1, int(max_results))
        self.timeout = max(0.05, float(timeout))

    def search(self, query: str, *, cancel_event: Event | None = None) -> DiscoveryResult:
        started = time.monotonic()
        normalized = _normalize_query(query)
        if not normalized:
            return DiscoveryResult(DiscoveryStatus.NO_RESULTS, DiscoveryKind.FOLDER, query=query, message="No folder query supplied.")
        candidates: list[FolderCandidate] = []
        truncated = False
        for root in self.roots:
            if not _safe_search_root(root):
                continue
            stack: list[tuple[Path, int]] = [(root, 0)]
            while stack:
                if cancel_event and cancel_event.is_set():
                    return _finish(DiscoveryStatus.CANCELLED, query, candidates, started, truncated)
                if time.monotonic() - started >= self.timeout:
                    truncated = True
                    break
                current, depth = stack.pop()
                try:
                    entries = list(os.scandir(current))
                except (OSError, PermissionError):
                    continue
                for entry in entries:
                    try:
                        if not entry.is_dir(follow_symlinks=False):
                            continue
                        path = Path(entry.path)
                        score = _score(normalized, path.name)
                        if score > 0:
                            try:
                                mtime = path.stat().st_mtime
                            except OSError:
                                mtime = None
                            candidates.append(FolderCandidate(path.name, str(path), modified_time=mtime, relevance=score))
                        if depth < self.max_depth:
                            stack.append((path, depth + 1))
                    except OSError:
                        continue
                    if len(candidates) >= self.max_results:
                        truncated = True
                        break
                if len(candidates) >= self.max_results:
                    break
            if cancel_event and cancel_event.is_set():
                return _finish(DiscoveryStatus.CANCELLED, query, candidates, started, truncated)
            if len(candidates) >= self.max_results or truncated:
                break
        if cancel_event and cancel_event.is_set():
            return _finish(DiscoveryStatus.CANCELLED, query, candidates, started, truncated)
        candidates.sort(key=lambda item: (-item.relevance, item.name.casefold(), item.path.casefold()))
        candidates = candidates[:self.max_results]
        status = DiscoveryStatus.AMBIGUOUS if len(candidates) > 1 else DiscoveryStatus.SUCCESS if candidates else DiscoveryStatus.NO_RESULTS
        return _finish(status, query, candidates, started, truncated)


def _finish(status, query, candidates, started, truncated=False):
    message = "Multiple matching folders found." if status is DiscoveryStatus.AMBIGUOUS else "Folder found." if candidates else "No matching folders found."
    return DiscoveryResult(status, DiscoveryKind.FOLDER, tuple(candidates), message, str(query), truncated, time.monotonic() - started)
