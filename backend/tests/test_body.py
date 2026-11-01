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


def test_truncates_to_max() -> None:
    assert len(clean_body("x" * 5000)) == MAX_CHARS


def test_empty() -> None:
    assert clean_body("") == ""
