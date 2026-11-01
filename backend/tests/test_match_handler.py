
from agent.match.handler import apply_classified
from domain.enums import EmailType, FirmType, FurthestStage, Status
from store.repository import Repository

UID = "u1"


def _classified(
    email_type: EmailType,
    *,
    company: str,
    role: str | None = None,
    date: str = "2026-10-10T09:00:00+00:00",
    msg_id: str = "m1",
    imid: str = "imid-1",
    conversation_id: str | None = None,
    is_job: bool = True,
    confidence: float = 0.9,
    requisition_id: str | None = None,
) -> dict:
    return {
        "facts": {
            "is_job_application_email": is_job,
            "email_type": email_type.value,
            "company": company,
            "role": role,
            "requisition_id": requisition_id,
            "summary": f"{email_type.value} from {company}",
            "confidence": confidence,
        },
        "email_date": date,
        "message_id": msg_id,
        "internet_message_id": imid,
        "conversation_id": conversation_id,
        "web_link": "https://outlook.office.com/mail/id/1",
    }


def test_creates_new_application_from_confirmation(repo: Repository) -> None:
    out = apply_classified(
        repo, UID, [_classified(EmailType.CONFIRMATION, company="Citi", role="Analyst")]
    )
    assert out["new_apps"] == 1
    apps = repo.list_applications(UID)
    assert len(apps) == 1
    assert apps[0].company == "Citi"
    assert apps[0].firm_type == FirmType.INVESTMENT_BANK  # from firm directory
    assert apps[0].status == Status.AWAITING_RESPONSE


def test_second_email_updates_same_application(repo: Repository) -> None:
    apply_classified(
        repo, UID,
        [_classified(EmailType.CONFIRMATION, company="Optiver", role="Trader",
                     date="2026-10-01T09:00:00+00:00", msg_id="m1", imid="i1")],
    )
    out = apply_classified(
        repo, UID,
        [_classified(EmailType.INTERVIEW_INVITE, company="Optiver", role="Trader",
                     date="2026-10-10T09:00:00+00:00", msg_id="m2", imid="i2")],
    )
    apps = repo.list_applications(UID)
    assert len(apps) == 1  # matched, not duplicated
    assert apps[0].status == Status.INTERVIEW
    assert apps[0].furthest_stage == FurthestStage.INTERVIEW
    assert out["status_changes"] == 1


def test_events_appended_to_timeline(repo: Repository) -> None:
    apply_classified(
        repo, UID, [_classified(EmailType.CONFIRMATION, company="Maven", role="Quant")]
    )
    app = repo.list_applications(UID)[0]
    events = repo.list_events(UID, app.app_id)
    assert len(events) == 1
    assert events[0].web_link == "https://outlook.office.com/mail/id/1"


def test_non_job_email_marked_processed_no_app(repo: Repository) -> None:
    out = apply_classified(
        repo, UID,
        [_classified(EmailType.OTHER, company="Spam", is_job=False, imid="i9")],
    )
    assert out["new_apps"] == 0
    assert repo.list_applications(UID) == []
    assert repo.is_processed(UID, "i9") is True


def test_requisition_id_matches_existing(repo: Repository) -> None:
    apply_classified(
        repo, UID,
        [_classified(EmailType.CONFIRMATION, company="Barclays", role="Markets",
                     requisition_id="REQ-7", imid="i1", msg_id="m1")],
    )
    # a differently-worded email but same requisition id must match
    apply_classified(
        repo, UID,
        [_classified(EmailType.REJECTION, company="Barclays PLC", role="Markets Division",
                     requisition_id="REQ-7", date="2026-10-20T09:00:00+00:00",
                     imid="i2", msg_id="m2")],
    )
    apps = repo.list_applications(UID)
    assert len(apps) == 1
    assert apps[0].status == Status.REJECTED
