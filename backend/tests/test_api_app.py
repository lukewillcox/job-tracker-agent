import json

import pytest

from api.app import handler
from api.session import issue_session
from domain.enums import FirmType, Status
from domain.models import Application, User
from store.repository import Repository

SIGNING_KEY = "test-signing-key"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TABLE_NAME", "JobTracker-test")
    monkeypatch.setenv("SESSION_SIGNING_KEY", SIGNING_KEY)
    # reset the cached repository so it binds to the moto table
    from store import client

    client.get_repository.cache_clear()


def _seed(repo: Repository) -> None:
    repo.put_user(User(user_id="u1", email="a@x.com", name="Ada"))
    repo.put_application(
        repo_user := "u1",
        Application(
            app_id="a1",
            company="Citi",
            company_norm="citi",
            firm_type=FirmType.INVESTMENT_BANK,
            status=Status.AWAITING_RESPONSE,
        ),
    )
    _ = repo_user


def _event(method: str, path: str, *, cookie: str | None = None, xrw: bool = True) -> dict:
    headers = {}
    if cookie is not None:
        headers["cookie"] = f"jt_session={cookie}"
    if xrw:
        headers["x-requested-with"] = "fetch"
    return {
        "rawPath": path,
        "headers": headers,
        "requestContext": {"http": {"method": method}},
    }


def _session() -> str:
    return issue_session("u1", SIGNING_KEY)


def test_unauthenticated_request_401(table: object, repo: Repository) -> None:
    _seed(repo)
    resp = handler(_event("GET", "/api/me", cookie=None))
    assert resp["statusCode"] == 401


def test_get_me(table: object, repo: Repository) -> None:
    _seed(repo)
    resp = handler(_event("GET", "/api/me", cookie=_session()))
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["email"] == "a@x.com"
    assert body["settings"]["timezone"] == "Europe/London"


def test_list_applications(table: object, repo: Repository) -> None:
    _seed(repo)
    resp = handler(_event("GET", "/api/applications", cookie=_session()))
    assert resp["statusCode"] == 200
    assert len(json.loads(resp["body"])) == 1


def test_application_detail_includes_timeline(table: object, repo: Repository) -> None:
    _seed(repo)
    resp = handler(_event("GET", "/api/applications/a1", cookie=_session()))
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["application"]["company"] == "Citi"
    assert body["timeline"] == []


def test_detail_404_for_unknown(table: object, repo: Repository) -> None:
    _seed(repo)
    resp = handler(_event("GET", "/api/applications/nope", cookie=_session()))
    assert resp["statusCode"] == 404


def test_analytics_shape(table: object, repo: Repository) -> None:
    _seed(repo)
    resp = handler(_event("GET", "/api/analytics", cookie=_session()))
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["summary"]["total"] == 1
    assert "funnel" in body and "by_firm_type" in body


def test_csrf_header_required_on_mutations(table: object, repo: Repository) -> None:
    _seed(repo)
    resp = handler(_event("DELETE", "/api/me", cookie=_session(), xrw=False))
    assert resp["statusCode"] == 403


def test_delete_account(table: object, repo: Repository) -> None:
    _seed(repo)
    resp = handler(_event("DELETE", "/api/me", cookie=_session()))
    assert resp["statusCode"] == 204
    assert repo.get_user("u1") is None


def test_auth_logout_is_public(table: object, repo: Repository) -> None:
    # logout needs no session and clears the cookie
    resp = handler(_event("POST", "/api/auth/logout"))
    assert resp["statusCode"] == 204
    assert "Max-Age=0" in resp["headers"]["Set-Cookie"]


def test_unknown_auth_route_404(table: object, repo: Repository) -> None:
    resp = handler(_event("GET", "/api/auth/bogus"))
    assert resp["statusCode"] == 404


def test_tenant_cannot_read_other_user(table: object, repo: Repository) -> None:
    _seed(repo)
    repo.put_user(User(user_id="u2", email="b@x.com"))
    repo.put_application(
        "u2",
        Application(app_id="secret", company="HRT", company_norm="hrt"),
    )
    # u1's session must not see u2's application
    resp = handler(_event("GET", "/api/applications/secret", cookie=_session()))
    assert resp["statusCode"] == 404
