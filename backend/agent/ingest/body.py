"""Clean an email body for classification.

Strips quoted replies and signatures, collapses whitespace, and truncates to
~1,500 chars to cut tokens. Truncation keeps the HEAD and the TAIL (joined by an
ellipsis), because an application email's verdict ("...we will not be
progressing") is usually in the first or last lines, with boilerplate in the
middle. Head-only truncation was observed to flip a rejection to a progress
update when the outcome sat after a long preamble. The cleaned text is used
transiently, never stored.
"""

from __future__ import annotations

import re

MAX_CHARS = 1500
_HEAD_CHARS = 1200
_TAIL_CHARS = 250  # leaves room for the " … " joiner within MAX_CHARS

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
    return _truncate(cleaned)


def _truncate(text: str) -> str:
    """Keep head + tail so an outcome line near either end survives."""

    if len(text) <= MAX_CHARS:
        return text
    head = text[:_HEAD_CHARS].rstrip()
    tail = text[-_TAIL_CHARS:].lstrip()
    return f"{head}\n…\n{tail}"
