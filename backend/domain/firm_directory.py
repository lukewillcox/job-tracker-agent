"""Firm directory: company name -> firm type, with alias lookup.

Also holds the shared company-name normalisation used by the matcher
(design.md "Normalisation").
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

from domain.enums import FirmType

_DIRECTORY_PATH = Path(__file__).with_name("firm_directory.yaml")

# Legal suffixes and descriptive tails stripped during normalisation.
# Order matters only in that all are removed; matched as whole words.
_SUFFIXES = (
    "plc",
    "ltd",
    "limited",
    "llp",
    "llc",
    "inc",
    "incorporated",
    "group",
    "and co",
    "co",
    "capital",
    "securities",
    "technologies",
    "technology",
    "partners",
    "advisory",
    "recruitment",
    "recruiting",
    "careers",
    "early careers",
    "management",
    "asset management",
    "investment management",
)

_SUFFIX_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(s) for s in sorted(_SUFFIXES, key=len, reverse=True)) + r")\b"
)
_NONWORD_RE = re.compile(r"[^a-z0-9]+")


def normalise(name: str) -> str:
    """Normalise a company name for matching and directory lookup.

    Lowercase, replace ``&`` with ``and``, strip legal suffixes and
    descriptive tails, collapse non-alphanumerics to single spaces.

    >>> normalise("BNP Paribas Recruitment")
    'bnp paribas'
    >>> normalise("Citigroup")
    'citi'
    >>> normalise("Rothschild & Co")
    'rothschild'
    """

    s = name.strip().lower()
    s = s.replace("&", " and ")
    # strip an email address down to a human-ish token if one slips in
    if "@" in s:
        s = s.split("@", 1)[0]
    s = _NONWORD_RE.sub(" ", s).strip()
    # remove suffixes repeatedly until stable (handles "x securities group")
    prev = None
    while prev != s:
        prev = s
        s = _SUFFIX_RE.sub(" ", s)
        s = re.sub(r"\s+", " ", s).strip()
    return s


class FirmDirectory:
    """In-memory firm directory with normalised-name and alias lookup."""

    def __init__(self, entries: dict[str, FirmType]) -> None:
        # entries maps already-normalised name -> firm type
        self._by_norm = entries

    @classmethod
    def from_yaml(cls, path: Path | None = None) -> FirmDirectory:
        raw = yaml.safe_load((path or _DIRECTORY_PATH).read_text(encoding="utf-8"))
        entries: dict[str, FirmType] = {}
        for firm in raw.get("firms", []):
            ft = FirmType(firm["firm_type"])
            names = [firm["name"], *firm.get("aliases", [])]
            for n in names:
                key = normalise(n)
                if key:
                    # first writer wins; canonical name is listed before aliases
                    entries.setdefault(key, ft)
        return cls(entries)

    def lookup(self, company: str) -> FirmType | None:
        """Return the firm type for a company name, or ``None`` if unknown."""

        return self._by_norm.get(normalise(company))

    def __len__(self) -> int:
        return len(self._by_norm)


@lru_cache(maxsize=1)
def default_directory() -> FirmDirectory:
    """Load and cache the bundled firm directory."""

    return FirmDirectory.from_yaml()
