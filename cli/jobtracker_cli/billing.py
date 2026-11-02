"""Token -> £ -> pints, for the local `status` beer tab.

Prices mirror the host's (Claude Haiku 4.5 on Bedrock, approximate). This is the
friend's local estimate of what their scans have cost the host; the host's
`jt-admin users` is the source of truth.
"""

from __future__ import annotations

import os

INPUT_USD_PER_MTOK = float(os.environ.get("CLASSIFY_INPUT_USD_PER_MTOK", "1.0"))
OUTPUT_USD_PER_MTOK = float(os.environ.get("CLASSIFY_OUTPUT_USD_PER_MTOK", "5.0"))
USD_TO_GBP = float(os.environ.get("USD_TO_GBP", "0.79"))
PINT_GBP = float(os.environ.get("PINT_GBP", "6.50"))


def cost_gbp(input_tokens: int, output_tokens: int) -> float:
    usd = (
        input_tokens / 1_000_000 * INPUT_USD_PER_MTOK
        + output_tokens / 1_000_000 * OUTPUT_USD_PER_MTOK
    )
    return round(usd * USD_TO_GBP, 4)


def beers(gbp: float) -> float:
    return round(gbp / PINT_GBP, 1) if PINT_GBP > 0 else 0.0
