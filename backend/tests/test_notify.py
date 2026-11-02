import datetime as dt

import pytest

from api import notify
from domain.enums import Status
from domain.models import Application, User
from store.repository import Repository


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TABLE_NAME", "JobTracker-test")
    monkeypatch.setenv("SES_FROM", "no-reply@mail.example.com")
    from store import client

    client.get_repository.cache_clear()


def _seed(repo: Repository) -> None:
    repo.put_user(User(user_id="u1", email="luke.willcox@outlook.com"))
    repo.put_application(
        "u1",
        Application(
            app_id="a1",
            company="Citi",
            company_norm="citi",
            status=Status.CHECK_EMAIL,
        ),
    )


def test_no_changes_sends_nothing(table: object, repo: Repository) -> None:
    out = notify.handler({"user_id": "u1", "new_apps": 0, "status_changes": 0})
    assert out["sent"] is False
    assert out["reason"] == "no changes"


def test_report_sent_on_changes(
    table: object, repo: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(repo)
    captured: dict[str, str] = {}

    def fake_send(to: str, subject: str, body: str) -> str:
        captured.update(to=to, subject=subject, body=body)
        return "msg-1"

    monkeypatch.setattr("integrations.ses.send_email", fake_send)
    out = notify.handler({"user_id": "u1", "new_apps": 2, "status_changes": 1})
    assert out["sent"] is True
    assert captured["to"] == "luke.willcox@outlook.com"
    assert "2 new" in captured["subject"]
    assert "Check email: Citi" in captured["body"]


def test_ses_failure_is_swallowed(
    table: object, repo: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(repo)

    def boom(*_a: object, **_k: object) -> str:
        raise RuntimeError("recipient not verified (sandbox)")

    monkeypatch.setattr("integrations.ses.send_email", boom)
    out = notify.handler({"user_id": "u1", "new_apps": 1, "status_changes": 0})
    assert out["sent"] is False
    assert out["reason"] == "ses_error"  # scan not failed by email


def test_gone_quiet_appears_in_todo(
    table: object, repo: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo.put_user(User(user_id="u1", email="luke.willcox@outlook.com"))
    repo.put_application(
        "u1",
        Application(
            app_id="a1",
            company="Barclays",
            company_norm="barclays",
            status=Status.AWAITING_RESPONSE,
            last_update=dt.date.today() - dt.timedelta(days=30),
        ),
    )
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        "integrations.ses.send_email",
        lambda to, s, b: captured.update(body=b) or "m",
    )
    notify.handler({"user_id": "u1", "new_apps": 0, "status_changes": 1})
    assert "Gone quiet" in captured["body"]
