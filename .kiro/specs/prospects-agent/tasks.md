# Implementation Plan: Prospects Agent

Work top to bottom; run tests + ruff + mypy and commit after each task. Ask Luke before any `cdk deploy`.

- [x] 1. Profile
  - DONE: `cli/jobtracker_cli/profile.py` (`Profile` model, load/save `~/.jobtracker/profile.json` at 0600, defaults, prompt round-trip helpers). `jobtracker profile` shows the profile; `--edit` opens it in `$EDITOR`. `setup` asks the profile questions (skippable, each field defaulted). `uninstall` removes the profile. 10 tests; cli suite 26 green.
  - _Requirements: 1, 7.3_
- [x] 2. Server: search endpoint
  - DONE: `BraveApiKey` secret (`jobtracker/brave-api-key-{stage}`) in the classify stack, read-only IAM grant, `BRAVE_SECRET_ARN` env. `integrations/brave.py` (`BraveClient`, `SearchResult`, key read from Secrets Manager, past-month freshness). `classifyapi/prospects.py` generates 4-6 queries via Bedrock and server-side enforces a programme term + start year on every query. `POST /prospects/search` bills tokens to the beer tab, reserves queries against an atomic monthly cap (default 40) and logs counts only — never profile/query/result text. Tests in `test_prospects.py` + search-cap tests in `test_classifyapi_store.py`; backend suite 226 green, tsc + synth clean.
  - _Requirements: 2.2-2.5, 7.2_
- [x] 3. Server: rank endpoint
  - DONE: `ProspectStatus` enum, `ProspectFacts` LLM model (is_job + company/role/programme/location/closing_date + fit 1-5 + why), `Prospect` stored model. `prospects_rank_v1.md` prompt. `rank_prospects` in `prospects.py` ranks ≤10 results, one retry per result on schema failure then drop. `POST /prospects/rank` bills tokens to the beer tab, logs counts only. Handler + rank tests incl. no-content-in-logs; backend suite 235 green, tsc + synth clean.
  - _Requirements: 4_
- [x] 4. CLI prospects pipeline
  - DONE: `prospects_client.py` (search + rank, ≤10/batch, retries). `prospects.py` pipeline: dedupe by URL, `RESTRICTED_DOMAINS` guard (LinkedIn/UCL/Handshake etc. never fetched — hard re-check in `fetch_excerpt`), optional single polite GET (10s, no retries, UA, 4000-char cap) for non-restricted, rank, filter (fit≥3, programme match, exclusions, is_job), company+role cross-URL dedupe. Prospects stored in `localstore` (new `prospects` list), re-found rows refresh facts but keep the user's Status, New rows >60d expire. `jobtracker prospects [--quiet] [--no-fetch]` command; skips with a hint if no profile. 14 pipeline tests incl. "restricted URLs are never fetched"; cli suite 40 green.
  - _Requirements: 2.1, 2.6, 3, 4.3, 5.6_
- [x] 5. Sync with the tracker
  - DONE: new prospects matching an existing application are skipped (6.1, done in Task 4's `_matches_application`). `sync_prospects_with_applications` flips matching prospects to Applied; called from `run_scan` on both the fresh-messages path and the no-new-mail path (6.2). "Not for me" prospects are left alone. 3 sync tests; cli suite 43 green.
  - _Requirements: 6.1, 6.2_
- [ ] 6. Excel tab + import
  - `_build_prospects` sheet after Priorities in house style, hyperlinks, dropdown, sort, conditional formats; importer reads Status back (Not for me never re-added). Tests.
  - _Requirements: 5, 6.3, 6.4_
- [ ] 7. Schedule + status
  - Weekly prospects run in the launchd job; `jobtracker status` shows open prospects and last run. Tests.
  - _Requirements: 2.1, 7.4_
- [ ] 8. Synth, then ask Luke to deploy; end-to-end test on Luke's profile; confirm no profile/query/result content in CloudWatch logs.
- [ ] 9. Update README + the friends' share message (profile step).
