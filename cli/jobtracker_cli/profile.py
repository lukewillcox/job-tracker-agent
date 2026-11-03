"""User search profile for the Prospects agent.

A short description of what the user is looking for, stored locally in
``~/.jobtracker/profile.json``. It is only ever sent to the classify API inside
a prospects request and is never stored server-side (Requirement 1.3).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from jobtracker_cli.config import CONFIG_DIR

PROFILE_PATH = CONFIG_DIR / "profile.json"

ProgrammeType = Literal["Graduate", "Internship", "Both"]
RecencyType = Literal["week", "month"]
_DEFAULT_START_YEAR = 2027


class Profile(BaseModel):
    """The user's search preferences (design.md "Profile")."""

    model_config = ConfigDict(extra="ignore")

    programme: ProgrammeType = "Both"
    start_year: int = Field(default=_DEFAULT_START_YEAR, ge=2000, le=2100)
    degrees: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    target_roles: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=lambda: ["London"])
    exclude: list[str] = Field(default_factory=list)
    # how new a posting must be: searches are limited to the past week/month
    recency: RecencyType = "month"

    def max_age_days(self) -> int:
        """Oldest posting (by posted/opening date) kept on the Prospects tab."""

        return 7 if self.recency == "week" else 31

    @classmethod
    def load(cls, path: Path | None = None) -> Profile | None:
        """Load the profile, or ``None`` if the user hasn't created one."""

        p = path or PROFILE_PATH
        if not p.exists():
            return None
        return cls.model_validate_json(p.read_text())

    def save(self, path: Path | None = None) -> None:
        p = path or PROFILE_PATH
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.model_dump_json(indent=2))
        p.chmod(0o600)

    def is_empty(self) -> bool:
        """True when the user has given nothing to search on yet."""

        return not (self.degrees or self.skills or self.target_roles)


def profile_exists(path: Path | None = None) -> bool:
    return (path or PROFILE_PATH).exists()


def remove_profile(path: Path | None = None) -> None:
    (path or PROFILE_PATH).unlink(missing_ok=True)


# --- JSON helpers for round-tripping edits (list fields as comma text) ----
def profile_to_prompts(profile: Profile) -> dict[str, str]:
    """Render a profile as flat strings for interactive prompts."""

    return {
        "programme": profile.programme,
        "start_year": str(profile.start_year),
        "degrees": ", ".join(profile.degrees),
        "skills": ", ".join(profile.skills),
        "target_roles": ", ".join(profile.target_roles),
        "locations": ", ".join(profile.locations),
        "exclude": ", ".join(profile.exclude),
        "recency": profile.recency,
    }


def _split(csv: str) -> list[str]:
    return [item.strip() for item in csv.split(",") if item.strip()]


def profile_from_prompts(answers: dict[str, str]) -> Profile:
    """Build a Profile from flat prompt answers (inverse of to_prompts)."""

    programme = answers.get("programme", "Both").strip().title()
    if programme not in ("Graduate", "Internship", "Both"):
        programme = "Both"
    year_raw = answers.get("start_year", "").strip()
    start_year = int(year_raw) if year_raw.isdigit() else _DEFAULT_START_YEAR
    return Profile(
        programme=programme,  # type: ignore[arg-type]
        start_year=start_year,
        degrees=_split(answers.get("degrees", "")),
        skills=_split(answers.get("skills", "")),
        target_roles=_split(answers.get("target_roles", "")),
        locations=_split(answers.get("locations", "London")) or ["London"],
        exclude=_split(answers.get("exclude", "")),
        recency="week" if answers.get("recency", "").strip().lower() == "week" else "month",
    )
