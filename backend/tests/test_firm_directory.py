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
        # parenthetical qualifiers are stripped
        ("EY (UK)", "ey"),
        ("EY (Switzerland)", "ey"),
        ("Susquehanna (SIG)", "susquehanna"),
        ("GRB (employer not named)", "grb"),
        # "Bank" descriptive tail stripped
        ("Monzo Bank Limited", "monzo"),
    ],
)
def test_normalise(raw: str, expected: str) -> None:
    assert normalise(raw) == expected


def test_parenthetical_variants_merge_to_same_norm() -> None:
    assert normalise("EY (UK)") == normalise("EY (Switzerland)") == normalise("EY")


def test_bank_suffix_does_not_break_multiword_firms() -> None:
    # regression: stripping "bank" must not mangle these
    d = default_directory()
    assert d.lookup("Deutsche Bank") is FirmType.INVESTMENT_BANK
    assert d.lookup("Bank of America") is FirmType.INVESTMENT_BANK


def test_newly_added_firms() -> None:
    d = default_directory()
    assert d.lookup("BBVA") is FirmType.INVESTMENT_BANK
    assert d.lookup("Chevron") is FirmType.ENERGY_COMMODITIES
    assert d.lookup("Harris Williams") is FirmType.BOUTIQUE_INVESTMENT_BANK


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
