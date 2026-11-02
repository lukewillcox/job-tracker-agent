import datetime as dt

from domain.enums import DeadlineKind, EmailType, UserStatus
from domain.models import (
    Application,
    Deadline,
    EmailFacts,
    Event,
    ScanRun,
    User,
)
from store.repository import Repository

UID = "user-1"
OTHER = "user-2"


def _app(app_id: str, company: str = "Citi") -> Application:
    return Application(app_id=app_id, company=company, company_norm=company.lower())


def _event(app_id: str, when: dt.datetime) -> Event:
    return Event(
        app_id=app_id,
        email_type=EmailType.CONFIRMATION,
        summary="application received",
        email_date=when,
        facts=EmailFacts(
            is_job_application_email=True,
            email_type=EmailType.CONFIRMATION,
            confidence=0.9,
        ),
        prompt_version="v1",
        confidence=0.9,
        message_id="msg-1",
    )


def test_user_roundtrip(repo: Repository) -> None:
    user = User(user_id=UID, email="a@example.com", name="Ada")
    repo.put_user(user)
    loaded = repo.get_user(UID)
    assert loaded is not None
    assert loaded.email == "a@example.com"
    assert loaded.settings.timezone == "Europe/London"


def test_put_user_preserves_stored_secret(repo: Repository) -> None:
    # regression: a later put_user must NOT clobber the top-level refresh token
    user = User(user_id=UID, email="a@example.com")
    repo.put_user(user)
    repo.put_user_secret(UID, "ENC-TOKEN-BLOB")
    # mutate + save the profile again (as the ingest handler does for delta links)
    user.delta_links = {"inbox": "DELTA-1"}
    repo.put_user(user)
    assert repo.get_user_secret(UID) == "ENC-TOKEN-BLOB"
    assert repo.get_user(UID).delta_links == {"inbox": "DELTA-1"}  # type: ignore[union-attr]


def test_paused_user_removed_from_active_index(repo: Repository) -> None:
    repo.put_user(User(user_id=UID, email="a@x.com", status=UserStatus.ACTIVE))
    repo.put_user(User(user_id=UID, email="a@x.com", status=UserStatus.PAUSED))
    resp = repo._t.query(  # type: ignore[attr-defined]
        IndexName="GSI2",
        KeyConditionExpression="GSI2PK = :pk",
        ExpressionAttributeValues={":pk": "ACTIVE_USERS"},
    )
    assert all(i.get("GSI2SK") != f"USER#{UID}" for i in resp["Items"])


def test_get_missing_user_returns_none(repo: Repository) -> None:
    assert repo.get_user("nope") is None


def test_application_roundtrip_and_list(repo: Repository) -> None:
    repo.put_application(UID, _app("a1"))
    repo.put_application(UID, _app("a2", "Barclays"))
    apps = repo.list_applications(UID)
    assert {a.app_id for a in apps} == {"a1", "a2"}


def test_deleted_apps_excluded_by_default(repo: Repository) -> None:
    app = _app("a1")
    app.deleted_at = dt.datetime.now(dt.UTC)
    repo.put_application(UID, app)
    assert repo.list_applications(UID) == []
    assert len(repo.list_applications(UID, include_deleted=True)) == 1


def test_tenant_isolation(repo: Repository) -> None:
    repo.put_application(UID, _app("a1"))
    repo.put_application(OTHER, _app("b1"))
    assert [a.app_id for a in repo.list_applications(UID)] == ["a1"]
    assert [a.app_id for a in repo.list_applications(OTHER)] == ["b1"]
    assert repo.get_application(UID, "b1") is None  # cannot read other tenant


def test_events_listed_per_application(repo: Repository) -> None:
    t1 = dt.datetime(2026, 10, 1, 9, tzinfo=dt.UTC)
    t2 = dt.datetime(2026, 10, 5, 9, tzinfo=dt.UTC)
    e1 = _event("a1", t1)
    e2 = _event("a1", t2)
    e2.message_id = "msg-2"
    repo.put_event(UID, e1)
    repo.put_event(UID, e2)
    repo.put_event(UID, _event("a2", t1))
    events = repo.list_events(UID, "a1")
    assert len(events) == 2


def test_processed_message_dedupe(repo: Repository) -> None:
    assert repo.is_processed(UID, "imid-1") is False
    repo.mark_processed(UID, "imid-1", outcome="job", ttl=9999999999)
    assert repo.is_processed(UID, "imid-1") is True


def test_deadline_roundtrip(repo: Repository) -> None:
    d = Deadline(
        deadline_id="d1",
        app_id="a1",
        what="SHL assessment",
        due_at=dt.datetime(2026, 11, 2, 23, 59, tzinfo=dt.UTC),
        kind=DeadlineKind.EXPLICIT,
    )
    repo.put_deadline(UID, d)
    loaded = repo.list_deadlines(UID)
    assert len(loaded) == 1 and loaded[0].what == "SHL assessment"


def test_scan_roundtrip(repo: Repository) -> None:
    scan = ScanRun(
        started_at=dt.datetime(2026, 10, 9, 8, 41, tzinfo=dt.UTC),
        new_apps=2,
        status_changes=1,
        est_cost=0.0123,
    )
    repo.put_scan(UID, scan)
    loaded = repo.list_scans(UID)
    assert len(loaded) == 1
    assert loaded[0].est_cost == 0.0123  # float survived the round-trip


def test_active_user_indexed_in_gsi2(repo: Repository) -> None:
    repo.put_user(User(user_id=UID, email="a@x.com", status=UserStatus.ACTIVE))
    repo.put_user(User(user_id=OTHER, email="b@x.com", status=UserStatus.PAUSED))
    # GSI2 only indexes active users; query it directly
    resp = repo._t.query(  # type: ignore[attr-defined]
        IndexName="GSI2",
        KeyConditionExpression="GSI2PK = :pk",
        ExpressionAttributeValues={":pk": "ACTIVE_USERS"},
    )
    keys = {i["GSI2SK"] for i in resp["Items"]}
    assert keys == {f"USER#{UID}"}


def test_delete_user_data(repo: Repository) -> None:
    repo.put_user(User(user_id=UID, email="a@x.com"))
    repo.put_application(UID, _app("a1"))
    repo.put_event(UID, _event("a1", dt.datetime(2026, 10, 1, 9, tzinfo=dt.UTC)))
    repo.put_application(OTHER, _app("b1"))
    deleted = repo.delete_user_data(UID)
    assert deleted == 3
    assert repo.get_user(UID) is None
    assert repo.list_applications(UID) == []
    assert len(repo.list_applications(OTHER)) == 1  # other tenant untouched
