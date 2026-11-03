"""Tests for the Prospects agent Profile (Task 1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from jobtracker_cli.profile import (
    Profile,
    profile_exists,
    profile_from_prompts,
    profile_to_prompts,
    remove_profile,
)


def test_defaults() -> None:
    p = Profile()
    assert p.programme == "Both"
    assert p.start_year == 2027
    assert p.locations == ["London"]
    assert p.degrees == [] and p.skills == [] and p.target_roles == []
    assert p.is_empty() is True


def test_not_empty_with_roles() -> None:
    assert Profile(target_roles=["quant analyst"]).is_empty() is False


def test_load_missing_returns_none(tmp_path: Path) -> None:
    assert Profile.load(tmp_path / "nope.json") is None
    assert profile_exists(tmp_path / "nope.json") is False


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    p = Profile(
        programme="Graduate",
        start_year=2027,
        degrees=["MSc Quantum Technologies (UCL)"],
        skills=["Python", "statistics"],
        target_roles=["quantitative analyst", "trader"],
        locations=["London"],
        exclude=["sales", "insurance"],
    )
    p.save(path)
    assert profile_exists(path) is True
    loaded = Profile.load(path)
    assert loaded == p


def test_saved_file_is_private(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    Profile().save(path)
    assert (path.stat().st_mode & 0o777) == 0o600


def test_remove_profile(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    Profile().save(path)
    remove_profile(path)
    assert profile_exists(path) is False
    # removing an absent file is a no-op
    remove_profile(path)


def test_prompts_roundtrip() -> None:
    p = Profile(
        programme="Internship",
        start_year=2026,
        degrees=["BSc Chemistry"],
        skills=["Python", "C++"],
        target_roles=["quant researcher"],
        locations=["London", "New York"],
        exclude=["recruitment consultant"],
    )
    back = profile_from_prompts(profile_to_prompts(p))
    assert back == p


def test_prompts_parse_commas_and_whitespace() -> None:
    p = profile_from_prompts(
        {
            "programme": "graduate",  # lowercase -> normalised
            "start_year": "2028",
            "degrees": " MSc Physics ,  BSc Maths ",
            "skills": "",
            "target_roles": "trader",
            "locations": "London,",
            "exclude": "sales, , insurance",
        }
    )
    assert p.programme == "Graduate"
    assert p.start_year == 2028
    assert p.degrees == ["MSc Physics", "BSc Maths"]
    assert p.skills == []
    assert p.locations == ["London"]
    assert p.exclude == ["sales", "insurance"]


def test_prompts_bad_programme_defaults_both() -> None:
    p = profile_from_prompts({"programme": "nonsense", "start_year": "x"})
    assert p.programme == "Both"
    assert p.start_year == 2027  # non-numeric year -> default
    assert p.locations == ["London"]  # empty locations -> default


def test_invalid_start_year_rejected() -> None:
    with pytest.raises(ValueError):
        Profile(start_year=1800)
