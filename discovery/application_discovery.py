"""Non-executing Windows application discovery."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Mapping
from threading import Event
import time

from .models import ApplicationCandidate, DiscoveryKind, DiscoveryResult, DiscoveryStatus


class ApplicationDiscovery:
    def __init__(self, approved_apps: Mapping[str, object] | None = None,
                 *, start_menu: bool = True, registry: bool = True,
                 max_results: int = 20, timeout: float = 2.0) -> None:
        self.approved_apps = {str(k).casefold() for k in (approved_apps or {})}
        self.start_menu = bool(start_menu)
        self.registry = bool(registry)
        self.max_results = max(1, int(max_results))
        self.timeout = max(0.05, float(timeout))

    def search(self, query: str, *, cancel_event: Event | None = None) -> DiscoveryResult:
        started = time.monotonic()
        q = " ".join(str(query).casefold().split()).strip()
        if not q:
            return DiscoveryResult(DiscoveryStatus.NO_RESULTS, DiscoveryKind.APPLICATION, query=str(query), message="No application query supplied.")
        candidates: dict[tuple[str, str], ApplicationCandidate] = {}
        # Configured applications are safe discovery candidates, but their
        # Configured paths remain subject to the existing execution-layer checks.
        for approved_name in self.approved_apps:
            score = _app_score(q, approved_name)
            if score > 0:
                candidates[(approved_name.casefold(), "application")] = ApplicationCandidate(
                    name=approved_name, source="approved_config", relevance=min(1.0, score + 0.1), approved=True
                )
        if self.start_menu:
            for root in _start_menu_roots():
                self._scan_shortcuts(root, q, candidates, started, cancel_event)
                if _expired(started, self.timeout, cancel_event):
                    break
        if self.registry and os.name == "nt" and not _expired(started, self.timeout, cancel_event):
            self._scan_registry(q, candidates, started, cancel_event)

        if cancel_event and cancel_event.is_set():
            return DiscoveryResult(DiscoveryStatus.CANCELLED, DiscoveryKind.APPLICATION, tuple(candidates.values()), "Application discovery cancelled.", q, False, time.monotonic() - started)

        truncated = len(candidates) > self.max_results or time.monotonic() - started >= self.timeout
        values = sorted(candidates.values(), key=lambda c: (-c.relevance, c.name.casefold(), c.source))[:self.max_results]
        if not values:
            return DiscoveryResult(DiscoveryStatus.NO_RESULTS, DiscoveryKind.APPLICATION, query=q, message="No matching applications found.")
        status = DiscoveryStatus.AMBIGUOUS if len(values) > 1 else DiscoveryStatus.SUCCESS
        message = "Multiple matching applications found." if status is DiscoveryStatus.AMBIGUOUS else "Application found."
        return DiscoveryResult(status, DiscoveryKind.APPLICATION, tuple(values), message, q, truncated, time.monotonic() - started)

    def _scan_shortcuts(self, root: Path, query: str, out: dict, started: float, cancel_event: Event | None) -> None:
        if not root.exists() or not root.is_dir():
            return
        stack = [root]
        while stack and len(out) < self.max_results * 3:
            if _expired(started, self.timeout, cancel_event):
                return
            current = stack.pop()
            try:
                entries = list(os.scandir(current))
            except (OSError, PermissionError):
                continue
            for entry in entries:
                if _expired(started, self.timeout, cancel_event):
                    return
                try:
                    path = Path(entry.path)
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(path)
                        continue
                    if path.suffix.casefold() != ".lnk":
                        continue
                    name = path.stem
                    score = _app_score(query, name)
                    if score <= 0:
                        continue
                    key = (name.casefold(), "application")
                    candidate = ApplicationCandidate(name=name, shortcut_path=str(path), source="start_menu",
                                                     relevance=score, approved=name.casefold() in self.approved_apps)
                    existing = out.get(key)
                    if existing is not None and existing.source == "approved_config" and candidate.approved:
                        candidate = ApplicationCandidate(name=name, shortcut_path=str(path), source="start_menu",
                                                         relevance=max(existing.relevance, candidate.relevance), approved=True)
                    if existing is None or candidate.relevance >= existing.relevance:
                        out[key] = candidate
                except OSError:
                    continue

    def _scan_registry(self, query: str, out: dict, started: float, cancel_event: Event | None) -> None:
        try:
            import winreg
        except ImportError:
            return
        locations = (
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        )
        for hive, subkey in locations:
            try:
                with winreg.OpenKey(hive, subkey) as parent:
                    for index in range(winreg.QueryInfoKey(parent)[0]):
                        if _expired(started, self.timeout, cancel_event):
                            return
                        try:
                            child_name = winreg.EnumKey(parent, index)
                            with winreg.OpenKey(parent, child_name) as key:
                                display, _ = winreg.QueryValueEx(key, "DisplayName")
                                if not isinstance(display, str):
                                    continue
                                score = _app_score(query, display)
                                if score <= 0:
                                    continue
                                key_id = (display.casefold(), "application")
                                candidate = ApplicationCandidate(display, executable_path=None,
                                    source="registry", relevance=score, approved=display.casefold() in self.approved_apps)
                                existing = out.get(key_id)
                                if existing is None or candidate.relevance > existing.relevance:
                                    out[key_id] = candidate
                        except (OSError, PermissionError):
                            continue
            except (OSError, PermissionError):
                continue


def _start_menu_roots() -> Iterable[Path]:
    appdata = os.environ.get("APPDATA")
    programdata = os.environ.get("PROGRAMDATA")
    roots = []
    if appdata:
        roots.append(Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    if programdata:
        roots.append(Path(programdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    return roots


def _app_score(query: str, name: str) -> float:
    q, n = query.casefold(), name.casefold()
    if q == n:
        return 1.0
    if q in n:
        return 0.9
    tokens = [t for t in q.replace("-", " ").split() if t]
    if tokens and all(t in n for t in tokens):
        return 0.75
    return 0.0


def _expired(started: float, timeout: float, cancel_event: Event | None) -> bool:
    return bool(cancel_event and cancel_event.is_set()) or time.monotonic() - started >= timeout
