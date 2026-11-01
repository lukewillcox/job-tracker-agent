# Backend

Python 3.12 backend for the Job Application Tracker Agent.

## Layout

- `domain/` — Pydantic models, enums, firm directory (pure, no AWS).
- `store/` — DynamoDB single-table repository layer.
- `integrations/` — Microsoft Graph, Bedrock, SES, OneDrive clients.
- `agent/` — the scan pipeline: `ingest/`, `classify/`, `match/`, `prep/`, `prompts/`.
- `excel/` — workbook builder and edit importer (parity with the reference tracker).
- `api/` — Lambda HTTP API handlers.
- `tests/` — unit, integration and eval tests.

## Dev tooling

The project targets `uv`, but works with any PEP 517 tooling.

```bash
# with uv (preferred)
uv sync
uv run ruff check .
uv run mypy
uv run pytest

# with a plain venv
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"   # or: pip install -e . --group dev
ruff check .
mypy
pytest
```
