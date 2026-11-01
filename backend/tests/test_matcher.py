from agent.match.matcher import MatchMethod, match_email
from agent.match.normalise import normalise_role, token_set_ratio
from domain.enums import EmailType, Status
from domain.firm_directory import normalise as normalise_company
from domain.models import Application, EmailFacts


def _app(app_id: str, company: str, role: str | None = None, **kw: object) -> Application:
    return Application(
        app_id=app_id,
        company=company,
        company_norm=normalise_company(company),
        role=role,
        **kw,  # type: ignore[arg-type]
    )


def _facts(**kw: object) -> EmailFacts:
    base: dict[str, object] = {
        "is_job_application_email": True,
        "email_type": EmailType.PROGRESS_UPDATE,
        "confidence": 0.9,
    }
    base.update(kw)
    return EmailFacts(**base)  # type: ignore[arg-type]


def test_match_by_requisition_id_wins_first() -> None:
    apps = [_app("a1", "Barclays", requisition_ids=["REQ-123"])]
    res = match_email(_facts(company="Barclays", requisition_id="REQ-123"), None, apps)
    assert res.method == MatchMethod.REQUISITION_ID
    assert res.application is apps[0]


def test_match_by_conversation_id() -> None:
    apps = [_app("a1", "Citi", conversation_ids=["conv-xyz"])]
    res = match_email(_facts(company="Citi"), "conv-xyz", apps)
    assert res.method == MatchMethod.CONVERSATION_ID


def test_match_company_and_role_similarity() -> None:
    apps = [_app("a1", "BNP Paribas", role="2027 Global Markets Graduate Analyst")]
    facts = _facts(company="BNP Paribas Recruitment", role="Global Markets Graduate Analyst")
    res = match_email(facts, None, apps)
    assert res.method == MatchMethod.COMPANY_AND_ROLE


def test_two_roles_same_company_do_not_collide() -> None:
    apps = [
        _app("a1", "BNP Paribas", role="Research Analyst", status=Status.AWAITING_RESPONSE),
        _app("a2", "BNP Paribas", role="Trading Analyst", status=Status.AWAITING_RESPONSE),
    ]
    # role-specific email should match the right one, not fall to single-open
    res = match_email(_facts(company="BNP Paribas", role="Trading Analyst"), None, apps)
    assert res.method == MatchMethod.COMPANY_AND_ROLE
    assert res.application is not None and res.application.app_id == "a2"


def test_single_open_application_fallback() -> None:
    apps = [_app("a1", "Optiver", role=None, status=Status.AWAITING_RESPONSE)]
    # no role on the email, but only one open app at Optiver
    res = match_email(_facts(company="Optiver"), None, apps)
    assert res.method == MatchMethod.SINGLE_OPEN_APP


def test_single_open_skipped_when_two_open() -> None:
    apps = [
        _app("a1", "Optiver", role="Trader", status=Status.AWAITING_RESPONSE),
        _app("a2", "Optiver", role="Researcher", status=Status.ASSESSMENT_STAGE),
    ]
    res = match_email(_facts(company="Optiver", email_type=EmailType.PROGRESS_UPDATE), None, apps)
    assert res.method == MatchMethod.NONE  # ambiguous, progress_update can't create


def test_new_application_for_confirmation() -> None:
    res = match_email(
        _facts(company="Jane Street", email_type=EmailType.CONFIRMATION), None, []
    )
    assert res.method == MatchMethod.NEW
    assert res.application is None


def test_no_match_and_non_creating_type_is_none() -> None:
    res = match_email(
        _facts(company="Unknown Co", email_type=EmailType.PROGRESS_UPDATE), None, []
    )
    assert res.method == MatchMethod.NONE


def test_deleted_applications_are_ignored() -> None:
    import datetime as dt

    apps = [_app("a1", "Citi", requisition_ids=["REQ-1"], deleted_at=dt.datetime.now(dt.UTC))]
    res = match_email(
        _facts(company="Citi", requisition_id="REQ-1", email_type=EmailType.CONFIRMATION),
        None,
        apps,
    )
    assert res.method == MatchMethod.NEW  # the deleted one is not matched


def test_token_set_ratio_order_independent() -> None:
    assert token_set_ratio("quant researcher intern", "intern quant researcher") == 1.0
    assert token_set_ratio("", "") == 1.0
    assert token_set_ratio("a", "") == 0.0


def test_normalise_role_drops_years_and_stopwords() -> None:
    assert normalise_role("2027 Graduate Analyst Programme") == "graduate analyst"
