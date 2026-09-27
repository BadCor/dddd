"""Safe text preparation for Stage 6 TTS."""
from __future__ import annotations

import re

from .result import TTSTextError

_MAX_TTS_CHARS = 2000
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_text(text: str, *, max_chars: int = _MAX_TTS_CHARS) -> str:
    if not isinstance(text, str):
        raise TTSTextError("Text-to-Speech input must be text.")
    normalized = _CONTROL_RE.sub(" ", text)
    normalized = " ".join(normalized.split())
    if not normalized:
        raise TTSTextError("Text-to-Speech input is empty.")
    limit = max(1, min(int(max_chars), _MAX_TTS_CHARS))
    if len(normalized) > limit:
        normalized = normalized[: max(0, limit - 3)].rstrip() + "..."
    return normalized
