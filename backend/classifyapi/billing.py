"""Translate token usage into money and, more importantly, beers.

Prices are Claude Haiku 4.5 on Bedrock (per 1M tokens). They drift, so they are
overridable via env for the admin report. GBP via a fixed USD->GBP rate (also
overridable). A "beer" is a pint; the host sets the local price.
"""

from __future__ import annotations

import os

# USD per 1M tokens (Claude Haiku 4.5 on Bedrock, approximate — override in env).
INPUT_USD_PER_MTOK = float(os.environ.get("CLASSIFY_INPUT_USD_PER_MTOK", "1.0"))
OUTPUT_USD_PER_MTOK = float(os.environ.get("CLASSIFY_OUTPUT_USD_PER_MTOK", "5.0"))
USD_TO_GBP = float(os.environ.get("USD_TO_GBP", "0.79"))
PINT_GBP = float(os.environ.get("PINT_GBP", "6.50"))  # a London pint, sadly


def cost_gbp(input_tokens: int, output_tokens: int) -> float:
    usd = (
        input_tokens / 1_000_000 * INPUT_USD_PER_MTOK
        + output_tokens / 1_000_000 * OUTPUT_USD_PER_MTOK
    )
    return round(usd * USD_TO_GBP, 4)


def beers(gbp: float) -> float:
    """How many pints that spend is worth, to one decimal."""

    return round(gbp / PINT_GBP, 1) if PINT_GBP > 0 else 0.0
