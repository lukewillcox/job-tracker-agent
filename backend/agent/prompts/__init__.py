"""Versioned prompt files, loaded by the classifier and prep generator."""

from __future__ import annotations

from functools import cache
from pathlib import Path

_DIR = Path(__file__).parent


@cache
def load_prompt(version: str) -> str:
    """Load a prompt by version id, e.g. ``classify_v1``."""

    return (_DIR / f"{version}.md").read_text(encoding="utf-8")
