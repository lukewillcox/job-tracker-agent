"""Cheap prefilter: decide whether a message is worth sending to the model.

Uses only the subject, sender and ``bodyPreview`` (never the full body), so it
is free of model cost. A message passes when:

  - the sender domain is a known applicant-tracking system (or the user's known
    application senders), OR
  - the subject/preview matches the keyword regex,

AND the sender is not on the blocklist (job alerts, marketing, newsletters,
university admissions) and the user has not marked the sender "not a job email"
(Requirement 3.1, design.md "Prefilter").

Target: keep at least 80% of non-job messages away from the model
(Requirement 15.2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

__all__ = ["PrefilterConfig", "PrefilterDecision", "prefilter"]

# Applicant-tracking system sending domains (Requirement 3.1 + design).
ATS_DOMAINS: frozenset[str] = frozenset(
    {
        "myworkday.com",
        "greenhouse-mail.io",
        "greenhouse.io",
        "ashbyhq.com",
        "tal.net",
        "jobs2web.com",
        "smartrecruiters.com",
        "lever.co",
        "hire.lever.co",
        "eu.greenhouse-mail.io",
        "successfactors.com",
        "icims.com",
        "oraclecloud.com",
        "brassring.com",
        "avature.net",
    }
)

# Keyword regex over subject + preview.
_KEYWORDS = (
    r"application",
    r"applying",
    r"applied",
    r"unfortunately",
    r"interview",
    r"assessment",
    r"candidate",
    r"offer",
    r"next steps",
    r"shortlist",
    r"video interview",
    r"online test",
    r"hirevue",
    r"shl",
    r"pymetrics",
    r"arctic shores",
    r"codility",
    r"hackerrank",
    r"testgorilla",
)
_KEYWORD_RE = re.compile(r"\b(?:" + "|".join(_KEYWORDS) + r")\b", re.IGNORECASE)

# Blocklist sender domains (job alerts, marketing, newsletters, admissions).
_BLOCKLIST_DOMAINS: frozenset[str] = frozenset(
    {
        "linkedin.com",  # job alerts & premium marketing (jobalerts-noreply@linkedin.com)
        "jobs-listings.linkedin.com",
        "e.linkedin.com",
        "totaljobs.com",
        "grb.uk.com",
        "brightnetwork.co.uk",  # note: real application reminders handled below
        "indeed.com",
        "reed.co.uk",
        "glassdoor.com",
        "ucas.com",
    }
)

# University admissions domains never count as job applications.
_UNI_ADMISSIONS_RE = re.compile(r"(?:admissions|study|postgraduate|msc|undergraduate)@")

# Obvious one-time-passcode / 2FA subjects.
_OTP_RE = re.compile(
    r"\b(?:verification code|one-time|otp|security code|2fa|two-factor|passcode)\b",
    re.IGNORECASE,
)


@dataclass
class PrefilterConfig:
    """Per-user prefilter configuration."""

    # extra sender domains the user has confirmed send real application emails
    known_application_senders: set[str] = field(default_factory=set)
    # senders the user marked "not a job email" (negative feedback, Req 12.4)
    negative_senders: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class PrefilterDecision:
    passed: bool
    reason: str


def _domain(sender: str) -> str:
    sender = sender.strip().lower()
    return sender.rsplit("@", 1)[-1] if "@" in sender else sender


def prefilter(
    sender: str,
    subject: str,
    body_preview: str,
    config: PrefilterConfig | None = None,
) -> PrefilterDecision:
    """Return whether a message should go to the classifier, with a reason."""

    cfg = config or PrefilterConfig()
    sender_l = sender.strip().lower()
    domain = _domain(sender_l)
    haystack = f"{subject}\n{body_preview}"

    # Hard negatives first (these override keyword hits).
    if sender_l in cfg.negative_senders or domain in cfg.negative_senders:
        return PrefilterDecision(False, "user marked sender not-a-job-email")
    if _OTP_RE.search(subject):
        return PrefilterDecision(False, "one-time passcode / 2FA")
    if _UNI_ADMISSIONS_RE.search(sender_l):
        return PrefilterDecision(False, "university admissions sender")

    # Strong positives: trusted ATS or user-confirmed senders bypass keywords.
    if domain in ATS_DOMAINS:
        return PrefilterDecision(True, f"ATS domain {domain}")
    if sender_l in cfg.known_application_senders or domain in cfg.known_application_senders:
        return PrefilterDecision(True, "known application sender")

    # Blocklist (job alerts / marketing) — only after ATS/known-sender checks.
    if domain in _BLOCKLIST_DOMAINS:
        return PrefilterDecision(False, f"blocklisted domain {domain}")

    if _KEYWORD_RE.search(haystack):
        return PrefilterDecision(True, "keyword match")

    return PrefilterDecision(False, "no keyword or trusted sender")
