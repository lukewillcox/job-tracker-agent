"""Clean an email body for classification.

Strips quoted replies and signatures, collapses whitespace and truncates to
4,000 characters (design.md / tech.md: send the model only what it needs). The
cleaned text is used transiently and never persisted.
"""

from __future__ import annotations

import re

MAX_CHARS = 4000

# Lines that mark the start of a quoted reply / forwarded block.
_QUOTE_MARKERS = (
    re.compile(r"^\s*on .+ wrote:\s*$", re.IGNORECASE),
    re.compile(r"^\s*-{2,}\s*original message\s*-{2,}\s*$", re.IGNORECASE),
    re.compile(r"^\s*-{2,}\s*forwarded message\s*-{2,}\s*$", re.IGNORECASE),
    re.compile(r"^\s*from:\s.+", re.IGNORECASE),  # header block of a quoted mail
    re.compile(r"^\s*_{5,}\s*$"),  # Outlook's underscore divider
)

# Lines that mark the start of a signature.
_SIG_MARKERS = (
    re.compile(r"^\s*--\s*$"),  # RFC 3676 signature delimiter
    re.compile(r"^\s*sent from my \w+", re.IGNORECASE),
)


def clean_body(text: str) -> str:
    """Return the message body with quotes/signatures removed and truncated."""

    if not text:
        return ""
    lines = text.replace("\r\n", "\n").split("\n")
    kept: list[str] = []
    for line in lines:
        if any(m.match(line) for m in _QUOTE_MARKERS):
            break  # everything below is a quoted/forwarded reply
        if any(m.match(line) for m in _SIG_MARKERS):
            break  # everything below is a signature
        kept.append(line)

    cleaned = "\n".join(kept)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned[:MAX_CHARS]
