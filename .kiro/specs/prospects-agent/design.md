# Design: Prospects Agent

## Overview
```
jobtracker prospects (weekly via launchd)
  │ profile.json (local)
  ▼
POST /prospects/search ──▶ classify API Lambda
  │   1. Bedrock: profile → 4-6 queries
  │   2. Brave Search API (key in Secrets Manager), freshness = past month
  │   3. per-user monthly query cap (DynamoDB, same codes table)
  ◀── raw results: title, snippet, url, age
  │
  │ CLI: dedupe, drop restricted-fetch, optional single page fetch (non-restricted)
  ▼
POST /prospects/rank (batches of 10) ──▶ Bedrock: extract + fit 1-5 + reason
  ◀── structured prospects (+ token usage → beer tab)
  │
  ▼
localstore: prospects table  ⇄  applications (sync rules)
  ▼
Excel builder: "Prospective roles" sheet
```
Two endpoints, not one, so each stays well under the API Gateway 30 s limit.

## Profile (`~/.jobtracker/profile.json`)
```json
{
  "programme": "Graduate",
  "start_year": 2027,
  "degrees": ["MSc Quantum Technologies (UCL)", "BSc Chemistry"],
  "skills": ["Python", "statistics", "quantitative analysis", "C++"],
  "target_roles": ["quantitative analyst", "quant researcher", "trader", "investment analyst"],
  "locations": ["London"],
  "exclude": ["sales", "insurance", "recruitment consultant"]
}
```
Pydantic model `Profile` in `cli/jobtracker_cli/profile.py`; validated on load; defaults for missing fields.

## API contracts
`POST /prospects/search` body `{profile, max_queries}` → `{queries: [...], results: [{title, snippet, url, age, query}], queries_used, queries_left}`.
`POST /prospects/rank` body `{profile, results: [≤10]}` → `{prospects: [{url, company, role, programme, location, closing_date, fit, why, is_job}], tokens_in, tokens_out}`.
Both use the existing invite-code auth, usage recording and "no content in logs" rule. Search cap stored as `SEARCH#<yyyy-mm>` counter on the user's item.

## Restricted sites
`RESTRICTED_DOMAINS` in config (linkedin.com, *.ucl.ac.uk careers portals, myuclcareers, handshake, and anything that 401/403s). Restricted results are ranked from title + snippet only. Non-restricted pages: one GET, 10 s timeout, User-Agent `jobtracker/<version> (+repo url)`, respect robots.txt, text truncated to 4,000 chars before ranking.

## Matching to applications
Normalise company with the existing firm-directory aliases; role similarity = token-set ratio ≥ 80 (rapidfuzz, or a small stdlib implementation). Used both to skip new prospects and to flip existing prospects to Applied after each `scan`.

## Excel
New `_build_prospects(ws, prospects)` in `backend/excel/builder.py`, reusing `_hdr`, `_cf_fill`, borders and fonts. Widths: Found 11, Company 22, Role 40, Programme 12, Location 14, Closing 12, Fit 6, Why 40, Link 12 ("Open" hyperlink), Source 12, Status 12. Conditional formats: closing ≤7 days amber; closing < today grey font; Status Applied/Not for me grey font. Importer reads Status back by Link/URL key.

## Cost
4-6 Brave queries/week/user ≈ 25/month; free credit ≈ 1,000/month → ~40 users. Ranking ≈ 30 results × ~600 tokens ≈ 20k tokens/week/user on the Haiku-class model.

## Testing
Unit: profile validation; query generation prompt contract (mocked Bedrock); restricted-domain guard (never fetched); dedupe; fit filtering; application matching; Excel sheet styling and sort; importer round-trip of Status. API: cap enforcement, auth, no content in logs (log capture test). All without network (Brave + Bedrock mocked).
