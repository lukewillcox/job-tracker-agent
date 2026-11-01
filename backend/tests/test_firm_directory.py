import pytest

from domain.enums import FirmType
from domain.firm_directory import default_directory, normalise


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("BNP Paribas Recruitment", "bnp paribas"),
        # "Citigroup" is one token; the Citi mapping comes from the alias list,
        # proven in test_lookup_known_firms, not from suffix stripping.
        ("Citigroup", "citigroup"),
        ("Rothschild & Co", "rothschild"),
        ("Maven Securities", "maven"),
        ("G-Research", "g research"),
        ("warburgpincus@dartmouthpartners.com", "warburgpincus"),
        ("  Optiver  ", "optiver"),
    ],
)
def test_normalise(raw: str, expected: str) -> None:
    assert normalise(raw) == expected


def test_lookup_known_firms() -> None:
    d = default_directory()
    assert d.lookup("BNP Paribas") is FirmType.INVESTMENT_BANK
    assert d.lookup("Citigroup") is FirmType.INVESTMENT_BANK
    assert d.lookup("Maven Securities") is FirmType.TRADING_FIRM
    assert d.lookup("Quantbot Technologies") is FirmType.HEDGE_FUND
    assert d.lookup("EY UK") is FirmType.PROFESSIONAL_SERVICES
    assert d.lookup("BCG") is FirmType.CONSULTING
    assert d.lookup("Circeus") is FirmType.UNCONFIRMED


def test_lookup_aliases_resolve_to_canonical_type() -> None:
    d = default_directory()
    assert d.lookup("JPMorgan Chase") is FirmType.INVESTMENT_BANK
    assert d.lookup("Susquehanna") is FirmType.TRADING_FIRM


def test_lookup_unknown_returns_none() -> None:
    assert default_directory().lookup("Totally Made Up Co") is None


def test_directory_non_empty() -> None:
    assert len(default_directory()) > 100
