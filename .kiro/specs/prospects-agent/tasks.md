# Implementation Plan: Prospects Agent

Work top to bottom; run tests + ruff + mypy and commit after each task. Ask Luke before any `cdk deploy`.

- [x] 1. Profile
  - DONE: `cli/jobtracker_cli/profile.py` (`Profile` model, load/save `~/.jobtracker/profile.json` at 0600, defaults, prompt round-trip helpers). `jobtracker profile` shows the profile; `--edit` opens it in `$EDITOR`. `setup` asks the profile questions (skippable, each field defaulted). `uninstall` removes the profile. 10 tests; cli suite 26 green.
  - _Requirements: 1, 7.3_
- [x] 2. Server: search endpoint
  - DONE: `BraveApiKey` secret (`jobtracker/brave-api-key-{stage}`) in the classify stack, read-only IAM grant, `BRAVE_SECRET_ARN` env. `integrations/brave.py` (`BraveClient`, `SearchResult`, key read from Secrets Manager, past-month freshness). `classifyapi/prospects.py` generates 4-6 queries via Bedrock and server-side enforces a programme term + start year on every query. `POST /prospects/search` bills tokens to the beer tab, reserves queries against an atomic monthly cap (default 40) and logs counts only — never profile/query/result text. Tests in `test_prospects.py` + search-cap tests in `test_classifyapi_store.py`; backend suite 226 green, tsc + synth clean.
  - _Requirements: 2.2-2.5, 7.2_
- [ ] 3. Server: rank endpoint
  - `POST /prospects/rank`: batch of ≤10 results → extraction + fit + reason + is_job; tokens billed to the beer tab. Tests.
  - _Requirements: 4_
- [ ] 4. CLI prospects pipeline
  - `jobtracker prospects`: call search, dedupe, restricted-domain guard, optional single polite page fetch, call rank in batches, filter (fit ≥3, programme match, exclusions, is_job).
  - Store prospects in `localstore` (new table), keep existing rows, expire New rows after 60 days. Tests incl. "restricted URLs are never fetched".
  - _Requirements: 2.1, 2.6, 3, 4.3, 5.6_
- [ ] 5. Sync with the tracker
  - Skip prospects matching existing applications; after each `scan`, flip matching prospects to Applied. Tests.
  - _Requirements: 6.1, 6.2_
- [ ] 6. Excel tab + import
  - `_build_prospects` sheet after Priorities in house style, hyperlinks, dropdown, sort, conditional formats; importer reads Status back (Not for me never re-added). Tests.
  - _Requirements: 5, 6.3, 6.4_
- [ ] 7. Schedule + status
  - Weekly prospects run in the launchd job; `jobtracker status` shows open prospects and last run. Tests.
  - _Requirements: 2.1, 7.4_
- [ ] 8. Synth, then ask Luke to deploy; end-to-end test on Luke's profile; confirm no profile/query/result content in CloudWatch logs.
- [ ] 9. Update README + the friends' share message (profile step).
