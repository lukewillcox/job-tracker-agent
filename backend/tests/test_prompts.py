"""Guard that versioned prompt files exist and load.

These .md files are runtime assets (the classifier/prep loader reads them), not
docs — a regression that excludes them from the Lambda package would only show
up in production, so assert they load here.
"""

from agent.classify.classifier import PROMPT_VERSION
from agent.prompts import load_prompt


def test_classify_prompt_loads() -> None:
    text = load_prompt(PROMPT_VERSION)
    assert "record_email_facts" in text
    assert len(text) > 500


def test_prompt_version_is_classify_v1() -> None:
    assert PROMPT_VERSION == "classify_v1"
