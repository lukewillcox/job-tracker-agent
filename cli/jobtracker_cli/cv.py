"""Read a CV on the user's Mac and strip personal details before it's sent.

Supports PDF, Word (.docx) and plain text. Only the cleaned text is sent to the
host's API, once, to draft a search profile; the file itself never leaves the
machine and nothing is stored server-side.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

SUPPORTED = (".pdf", ".docx", ".txt", ".md")
MAX_CHARS = 15000


class CvError(ValueError):
    """The CV couldn't be found or read."""


def clean_path(raw: str) -> Path:
    """Tidy a path typed or dragged into Terminal (quotes, escaped spaces, ~)."""

    text = raw.strip().strip("'\"")
    text = re.sub(r"\\(.)", r"\1", text)  # Finder drag-drop escapes spaces as "\ "
    return Path(text).expanduser()


def read_cv_text(path: Path) -> str:
    if not path.exists() or not path.is_file():
        raise CvError(f"couldn't find a file at {path}")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED:
        raise CvError("please use a PDF, Word (.docx) or text file")
    try:
        if suffix == ".pdf":
            from pypdf import PdfReader

            text = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
        elif suffix == ".docx":
            text = _docx_text(path)
        else:
            text = path.read_text(encoding="utf-8", errors="ignore")
    except CvError:
        raise
    except Exception as exc:  # noqa: BLE001 — any parser failure = unreadable CV
        raise CvError(f"couldn't read the CV ({exc.__class__.__name__})") from exc
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    if len(text) < 200:
        raise CvError(
            "couldn't read enough text from the CV (is it a scanned image?). "
            "Try a Word or text version, or answer the questions instead."
        )
    return text


def _docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", " ", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    import html

    return html.unescape(text)


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"(?:https?://|www\.)\S+|\b(?:linkedin|github)\.com/\S+", re.I)
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d ()-]{8,}\d)(?!\w)")
_UK_POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}\b", re.I)


def redact(text: str) -> str:
    """Remove the name line, emails, phone numbers, links and UK postcodes.

    Also drops the address line (the line that held a postcode), since a CV's
    first lines are usually name + address + contact details.
    """

    lines = text.splitlines()
    out: list[str] = []
    name_dropped = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if not name_dropped:
            # the first real line of a CV is almost always the name
            name_dropped = True
            words = stripped.split()
            if len(words) <= 5 and not any(ch.isdigit() for ch in stripped):
                continue
        if _UK_POSTCODE.search(stripped):
            # address lines carry the postcode; drop the whole line
            stripped = _UK_POSTCODE.sub("", stripped)
            if len(stripped.split()) <= 8:
                continue
        stripped = _EMAIL.sub("[email]", stripped)
        stripped = _URL.sub("[link]", stripped)
        stripped = _PHONE.sub("[phone]", stripped)
        if stripped.replace("[email]", "").replace("[phone]", "").replace("[link]", "").strip(
            " ,|·•-"
        ) == "":
            continue  # a contact-details-only line
        out.append(stripped)
    return "\n".join(out)[:MAX_CHARS]
