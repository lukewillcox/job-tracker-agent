from domain.enums import EmailType
from domain.models import EmailFacts
from tests.eval.harness import evaluate, load_cases


def _oracle(case: dict) -> EmailFacts:
    """A perfect classifier that reads the label (tests the harness itself)."""

    label = case["label"]
    return EmailFacts(
        is_job_application_email=bool(label["is_job"]),
        email_type=EmailType(label["email_type"]),
        confidence=0.99,
    )


def _always_job(case: dict) -> EmailFacts:
    return EmailFacts(
        is_job_application_email=True,
        email_type=EmailType.CONFIRMATION,
        confidence=0.9,
    )


def test_set_loads() -> None:
    cases = load_cases()
    assert len(cases) >= 35
    # every id is unique
    assert len({c["id"] for c in cases}) == len(cases)


def test_set_covers_every_email_type() -> None:
    types = {c["label"]["email_type"] for c in load_cases() if c["label"]["is_job"]}
    expected = {e.value for e in EmailType} - {"other"}
    missing = expected - types
    assert missing == set(), f"email types not covered by the eval set: {missing}"


def test_set_has_not_job_cases() -> None:
    not_job = [c for c in load_cases() if not c["label"]["is_job"]]
    # admissions, event, alerts, marketing, recruiter spam, newsletter, OTP, 2FA...
    assert len(not_job) >= 8


def test_oracle_scores_perfectly() -> None:
    report = evaluate(_oracle)
    assert report.is_job_precision == 1.0
    assert report.is_job_recall == 1.0
    assert report.email_type_accuracy == 1.0
    assert report.meets_targets()


def test_harness_detects_false_positives() -> None:
    # classifying everything as a job email tanks precision
    report = evaluate(_always_job)
    assert report.is_job_precision < 1.0
    assert report.is_job_recall == 1.0  # it does catch all real ones
    assert not report.meets_targets()
