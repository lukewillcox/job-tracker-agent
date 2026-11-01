"""Classification evaluation harness.

Loads the labelled set and scores a classifier's predictions, reporting
precision/recall on "is a job application email" and accuracy on ``email_type``
(the status driver). Usable with the real Bedrock classifier or any callable
that maps a case dict to an :class:`EmailFacts`.

Run against Bedrock:
    CLASSIFIER_MODEL_ID=... uv run python -m tests.eval.harness

The CI gate (precision/recall >= 0.95, status >= 0.90) is only meaningful once
the set reaches >= 150 cases; see tasks.md.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from domain.models import EmailFacts

_SET = Path(__file__).with_name("labelled.jsonl")

Classifier = Callable[[dict[str, Any]], EmailFacts]


def load_cases() -> list[dict[str, Any]]:
    return [json.loads(line) for line in _SET.read_text().splitlines() if line.strip()]


@dataclass
class EvalReport:
    total: int
    is_job_precision: float
    is_job_recall: float
    email_type_accuracy: float

    def meets_targets(self, min_pr: float = 0.95, min_status: float = 0.90) -> bool:
        return (
            self.is_job_precision >= min_pr
            and self.is_job_recall >= min_pr
            and self.email_type_accuracy >= min_status
        )


def evaluate(classifier: Classifier, cases: list[dict[str, Any]] | None = None) -> EvalReport:
    cases = cases or load_cases()
    tp = fp = fn = 0
    type_correct = type_total = 0

    for case in cases:
        label = case["label"]
        facts = classifier(case)
        expected_job = bool(label["is_job"])
        predicted_job = facts.is_job_application_email

        if predicted_job and expected_job:
            tp += 1
        elif predicted_job and not expected_job:
            fp += 1
        elif not predicted_job and expected_job:
            fn += 1

        # email-type accuracy only on true job emails
        if expected_job:
            type_total += 1
            if facts.email_type.value == label["email_type"]:
                type_correct += 1

    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    accuracy = type_correct / type_total if type_total else 1.0
    return EvalReport(len(cases), precision, recall, accuracy)


def bedrock_classifier(case: dict[str, Any]) -> EmailFacts:
    """A classifier that calls the real Bedrock classifier for a case."""

    import os

    from agent.classify.classifier import ClassifyInput, classify_email
    from integrations.bedrock import BedrockClient

    result = classify_email(
        BedrockClient(),
        os.environ["CLASSIFIER_MODEL_ID"],
        ClassifyInput(
            sender=case["sender"],
            subject=case["subject"],
            body_text=case["body"],
            received=dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC),
            folder=case.get("folder", "inbox"),
        ),
    )
    return result.facts


if __name__ == "__main__":  # pragma: no cover
    report = evaluate(bedrock_classifier)
    print(json.dumps(report.__dict__, indent=2))
    print("meets targets:", report.meets_targets())
