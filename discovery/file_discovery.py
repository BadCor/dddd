"""Safe file discovery inside explicitly configured user/search roots."""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Iterable

from .models import DiscoveryKind, DiscoveryResult, DiscoveryStatus, FileCandidate


class FileDiscovery:
    def __init__(self, roots: Iterable[str | Path], *, max_depth: int = 4,
                 max_results: int = 20, timeout: float = 2.0) -> None:
        self.roots = tuple(Path(r).expanduser() for r in roots)
        self.max_depth = max(0, int(max_depth))
        self.max_results = max(1, int(max_results))
        self.timeout = max(0.05, float(timeout))

    def search(self, query: str, *, extension: str | None = None,
               cancel_event: Event | None = None) -> DiscoveryResult:
        started = time.monotonic()
        normalized = _normalize_query(query)
        ext = _normalize_extension(extension)
        recent_mode, normalized_search = _recent_filter(normalized)
        if not normalized_search and not recent_mode:
            return _result(DiscoveryStatus.NO_RESULTS, "file", query, (), started)

        candidates: list[FileCandidate] = []
        truncated = False
        for root in self.roots:
            if not _safe_search_root(root):
                continue
            for path, depth in _walk(root, self.max_depth, started, self.timeout, cancel_event):
                if cancel_event and cancel_event.is_set():
                    return _result(DiscoveryStatus.CANCELLED, DiscoveryKind.FILE, query, tuple(candidates), started, truncated)
                if time.monotonic() - started >= self.timeout:
                    truncated = True
                    break
                try:
                    if not path.is_file():
                        continue
                    if ext and path.suffix.casefold() != ext:
                        continue
                    stat = path.stat()
                    if recent_mode and not _is_recent(stat.st_mtime, recent_mode):
                        continue
                    score = _score(normalized_search, path.name) if normalized_search else 0.65
                    if score <= 0:
                        continue
                    candidates.append(FileCandidate(
                        name=path.name, path=str(path), size=stat.st_size,
                        modified_time=stat.st_mtime, relevance=score,
                    ))
                except (OSError, PermissionError):
                    continue
                if len(candidates) >= self.max_results:
                    truncated = True
                    break
            if cancel_event and cancel_event.is_set():
                return _result(DiscoveryStatus.CANCELLED, DiscoveryKind.FILE, query, tuple(candidates), started, truncated)
            if len(candidates) >= self.max_results or time.monotonic() - started >= self.timeout:
                truncated = True
                break

        if cancel_event and cancel_event.is_set():
            return _result(DiscoveryStatus.CANCELLED, DiscoveryKind.FILE, query, tuple(candidates), started, truncated)

        candidates.sort(key=lambda item: (-item.relevance, -(item.modified_time or 0.0), item.name.casefold()))
        candidates = candidates[:self.max_results]
        status = DiscoveryStatus.AMBIGUOUS if len(candidates) > 1 else DiscoveryStatus.SUCCESS if candidates else DiscoveryStatus.NO_RESULTS
        message = "Multiple matching files found." if status is DiscoveryStatus.AMBIGUOUS else "File found." if candidates else "No matching files found."
        return _result(status, DiscoveryKind.FILE, query, tuple(candidates), started, truncated, message)


def _normalize_query(value: str) -> str:
    return " ".join(str(value).casefold().split()).strip('"\' ')


def _normalize_extension(value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    value = str(value).strip().casefold()
    return value if value.startswith(".") else "." + value


def _safe_search_root(root: Path) -> bool:
    try:
        if not root.exists() or not root.is_dir():
            return False
        resolved = root.resolve(strict=True)
        home = Path.home().resolve()
        if resolved == home or home in resolved.parents:
            return True
        return _looks_like_project_root(resolved)
    except (OSError, RuntimeError):
        return False


def _looks_like_project_root(path: Path) -> bool:
    # Explicit non-system roots are allowed when they are not Windows/system locations.
    blocked = {
        "windows", "program files", "program files (x86)", "programdata",
        "$recycle.bin", "system volume information", "recovery", "boot",
    }
    parts = {part.casefold() for part in path.parts}
    # Never treat a drive root itself as a searchable root.
    if path == Path(path.anchor):
        return False
    return not any(name in parts for name in blocked)


def _walk(root: Path, max_depth: int, started: float, timeout: float, cancel_event: Event | None):
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        if cancel_event and cancel_event.is_set():
            return
        if time.monotonic() - started >= timeout:
            return
        try:
            entries = list(os.scandir(current))
        except (OSError, PermissionError):
            continue
        for entry in entries:
            if cancel_event and cancel_event.is_set():
                return
            try:
                path = Path(entry.path)
                if entry.is_file(follow_symlinks=False):
                    yield path, depth
                elif entry.is_dir(follow_symlinks=False) and depth < max_depth:
                    stack.append((path, depth + 1))
            except OSError:
                continue


def _score(query: str, name: str) -> float:
    q = query.casefold()
    n = name.casefold()
    if q == n:
        return 1.0
    if q in n:
        return 0.9
    tokens = [token for token in q.replace("_", " ").replace("-", " ").split() if token]
    if not tokens:
        return 0.0
    matched = sum(token in n for token in tokens)
    return matched / len(tokens) * 0.75 if matched else 0.0


def _result(status, kind, query, candidates, started, truncated=False, message=""):
    kind = kind if isinstance(kind, DiscoveryKind) else DiscoveryKind(kind)
    return DiscoveryResult(status=status, kind=kind, candidates=candidates,
                           query=str(query), truncated=truncated,
                           elapsed_seconds=time.monotonic() - started,
                           message=message or status.value.replace("_", " ").capitalize())


def _recent_filter(query: str) -> tuple[str | None, str]:
    tokens = query.split()
    recent = None
    kept = []
    for token in tokens:
        if token in {"yesterday", "recent", "recently"}:
            recent = token
        elif token == "today":
            recent = "today"
        elif token not in {"downloaded", "download", "modified", "file"}:
            kept.append(token)
    return recent, " ".join(kept).strip()


def _is_recent(timestamp: float, mode: str) -> bool:
    current = datetime.now().date()
    date = datetime.fromtimestamp(timestamp).date()
    if mode == "today":
        return date == current
    if mode == "yesterday":
        return date == current - timedelta(days=1)
    return timestamp >= time.time() - 7 * 24 * 60 * 60
