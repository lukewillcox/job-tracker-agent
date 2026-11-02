from agent.ingest.body import MAX_CHARS, clean_body


def test_strips_quoted_reply_on_wrote() -> None:
    text = "Thanks for applying.\n\nOn Mon, 1 Oct 2026, Recruiter wrote:\n> old stuff"
    assert clean_body(text) == "Thanks for applying."


def test_strips_original_message_block() -> None:
    text = "We'd like to invite you.\n-----Original Message-----\nFrom: x"
    assert clean_body(text) == "We'd like to invite you."


def test_strips_signature_delimiter() -> None:
    text = "Please complete the test.\n--\nJane Doe\nTalent Team"
    assert clean_body(text) == "Please complete the test."


def test_strips_sent_from_my_phone() -> None:
    text = "Congratulations!\nSent from my iPhone"
    assert clean_body(text) == "Congratulations!"


def test_collapses_blank_lines() -> None:
    assert clean_body("a\n\n\n\nb") == "a\n\nb"


def test_truncates_to_about_max() -> None:
    # head + "…" + tail stays close to MAX_CHARS (a few joiner chars over the
    # head/tail split is fine)
    out = clean_body("x" * 5000)
    assert len(out) <= MAX_CHARS + 5
    assert "…" in out


def test_truncation_keeps_the_tail() -> None:
    # an outcome line at the very end must survive head+tail truncation
    body = "Dear applicant,\n" + ("filler line. " * 300) + "\nVERDICT: not progressing."
    out = clean_body(body)
    assert "VERDICT: not progressing." in out
    assert out.startswith("Dear applicant,")


def test_short_body_unchanged_by_truncation() -> None:
    assert clean_body("Short and sweet.") == "Short and sweet."


def test_empty() -> None:
    assert clean_body("") == ""
