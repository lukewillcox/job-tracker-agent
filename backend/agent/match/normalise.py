"""Normalisation helpers for matching.

Re-exports the shared company normalisation from the firm directory and adds
role-title normalisation and a token-set similarity ratio (a dependency-free
stand-in for rapidfuzz's token_set_ratio).
"""

from __future__ import annotations

import re

from domain.firm_directory import normalise as normalise_company

__all__ = ["normalise_company", "normalise_role", "token_set_ratio"]

# Noise words removed from role titles before comparison. Years and requisition
# cruft vary between emails for the same role, so they are dropped.
_ROLE_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "for",
        "and",
        "to",
        "in",
        "at",
        "role",
        "position",
        "programme",
        "program",
        "scheme",
        "opportunity",
        "vacancy",
        "job",
        "f",
        "m",
        "d",  # from "(f/m/d)" diversity tags once punctuation is stripped
    }
)
_YEAR_RE = re.compile(r"\b20\d{2}\b")
_NONWORD_RE = re.compile(r"[^a-z0-9]+")


def normalise_role(role: str | None) -> str:
    """Normalise a role title: lowercase, drop years, punctuation and stopwords."""

    if not role:
        return ""
    s = role.lower()
    s = _YEAR_RE.sub(" ", s)
    s = _NONWORD_RE.sub(" ", s)
    tokens = [t for t in s.split() if t and t not in _ROLE_STOPWORDS]
    return " ".join(tokens)


def token_set_ratio(a: str, b: str) -> float:
    """Return a 0..1 similarity based on shared tokens (order-independent).

    Mirrors the spirit of fuzzywuzzy/rapidfuzz ``token_set_ratio``: it compares
    the sets of tokens, so "Graduate Analyst Markets" and "Markets Graduate
    Analyst" score 1.0. Uses the Jaccard-style overlap over the larger set.

    >>> token_set_ratio("quant researcher intern", "intern quant researcher")
    1.0
    >>> token_set_ratio("", "")
    1.0
    """

    sa = set(a.split())
    sb = set(b.split())
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    intersection = sa & sb
    # Dice-style coefficient: rewards shared tokens, tolerant of extra words.
    return 2 * len(intersection) / (len(sa) + len(sb))
