from agent.ingest.prefilter import PrefilterConfig, prefilter


def test_ats_domain_passes_without_keywords() -> None:
    d = prefilter("no-reply@myworkday.com", "Your submission", "Thanks", None)
    assert d.passed is True
    assert "ATS" in d.reason


def test_keyword_match_passes() -> None:
    d = prefilter("careers@somefirm.com", "Invitation to online assessment", "", None)
    assert d.passed is True


def test_job_alert_blocklisted() -> None:
    d = prefilter("jobalerts-noreply@linkedin.com", "30 new jobs for you", "apply now", None)
    assert d.passed is False
    assert "blocklist" in d.reason


def test_otp_rejected_even_with_keyword() -> None:
    d = prefilter("security@bank.com", "Your verification code is 123456", "", None)
    assert d.passed is False


def test_university_admissions_rejected() -> None:
    d = prefilter("admissions@ucl.ac.uk", "Your application to MSc Finance", "", None)
    assert d.passed is False


def test_negative_sender_overrides_keyword() -> None:
    cfg = PrefilterConfig(negative_senders={"recruiter@spam.com"})
    d = prefilter("recruiter@spam.com", "Available for interview?", "", cfg)
    assert d.passed is False


def test_known_application_sender_passes() -> None:
    cfg = PrefilterConfig(known_application_senders={"talent@boutique.com"})
    d = prefilter("talent@boutique.com", "update", "", cfg)
    assert d.passed is True


def test_plain_newsletter_rejected() -> None:
    d = prefilter("news@fintechweekly.com", "This week in fintech", "stories", None)
    assert d.passed is False
