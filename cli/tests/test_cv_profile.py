"""Building a search profile from a CV (read, redact, draft, confirm)."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from jobtracker_cli import config as cfg
from jobtracker_cli import main as cli_main
from jobtracker_cli.cv import CvError, clean_path, read_cv_text, redact

CV = """Sam Taylor
12 Example Road, Leeds, LS1 4AB
sam.taylor@example.com | +44 7700 900123 | linkedin.com/in/samtaylor
EDUCATION
University of Leeds - BSc Mathematics, expected First, Sep 2024 - Jun 2027
Modules: Probability, Stochastic Processes, Numerical Methods in Python
EXPERIENCE
Summer analyst intern, Example Capital, Jun 2026 - Aug 2026
- Built Python and SQL tools to analyse trading data and automate reporting.
SKILLS: Python, SQL, Excel, R, statistics
"""


def test_redact_strips_name_and_contact_details() -> None:
    out = redact(CV)
    for secret in ("Sam Taylor", "sam.taylor@example.com", "7700 900123",
                   "LS1 4AB", "Example Road", "linkedin.com/in/samtaylor"):
        assert secret not in out
    assert "BSc Mathematics" in out and "Python, SQL" in out


def test_read_txt_and_docx(tmp_path: Path) -> None:
    txt = tmp_path / "cv.txt"
    txt.write_text(CV)
    assert "BSc Mathematics" in read_cv_text(txt)

    docx = tmp_path / "cv.docx"
    body = "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in CV.splitlines())
    with zipfile.ZipFile(docx, "w") as z:
        z.writestr("word/document.xml", f"<w:document><w:body>{body}</w:body></w:document>")
    assert "Stochastic Processes" in read_cv_text(docx)


def test_unreadable_cvs_give_friendly_errors(tmp_path: Path) -> None:
    with pytest.raises(CvError, match="couldn't find"):
        read_cv_text(tmp_path / "missing.pdf")
    bad = tmp_path / "cv.pages"
    bad.write_text("x")
    with pytest.raises(CvError, match="PDF, Word"):
        read_cv_text(bad)
    short = tmp_path / "short.txt"
    short.write_text("just a name")
    with pytest.raises(CvError, match="enough text"):
        read_cv_text(short)


def test_clean_path_handles_finder_drag_and_drop() -> None:
    assert str(clean_path("/Users/sam/My\\ CV.pdf ")) == "/Users/sam/My CV.pdf"
    assert str(clean_path("'/Users/sam/My CV.pdf'")) == "/Users/sam/My CV.pdf"


def test_friend_builds_profile_from_cv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """End to end: `jobtracker profile --from-cv` -> API draft -> confirm with Enter."""

    from jobtracker_cli import profile as prof

    monkeypatch.setattr(prof, "PROFILE_PATH", tmp_path / "profile.json")
    monkeypatch.setattr(cfg.Config, "load", classmethod(
        lambda cls: cls(username="sam", api_url="https://api.example")))
    monkeypatch.setattr(cfg, "get_invite_code", lambda: "jt_sam_x")

    sent: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, url: str, code: str) -> None:
            pass

        def extract_profile(self, cv_text: str) -> dict[str, Any]:
            sent["text"] = cv_text
            return {"programme": "Graduate", "start_year": 2027,
                    "degrees": ["BSc Mathematics (Leeds)"], "skills": ["Python", "SQL"],
                    "target_roles": ["quantitative analyst", "data analyst"],
                    "locations": ["Leeds", "London"]}

    import jobtracker_cli.prospects_client as pc
    monkeypatch.setattr(pc, "ProspectsClient", FakeClient)

    cv = tmp_path / "Sam CV.txt"
    cv.write_text(CV)
    # accept every suggestion (Enter x8), then add an exclusion
    answers = "\n" * 6 + "sales\n" + "\n"
    result = CliRunner().invoke(cli_main.cli, ["profile", "--from-cv", str(cv)], input=answers)
    assert result.exit_code == 0, result.output

    # only redacted text was sent
    assert "sam.taylor@example.com" not in sent["text"] and "Sam Taylor" not in sent["text"]
    saved = prof.Profile.load(tmp_path / "profile.json")
    assert saved is not None
    assert saved.programme == "Graduate"
    assert saved.degrees == ["BSc Mathematics (Leeds)"]
    assert saved.target_roles == ["quantitative analyst", "data analyst"]
    assert saved.locations == ["Leeds", "London"]
    assert saved.exclude == ["sales"]
