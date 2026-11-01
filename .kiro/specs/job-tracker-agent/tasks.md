# Implementation Plan

Work top to bottom. Each task should leave the project building and tests passing. Milestone 1 (tasks 1-9) reproduces today's personal agent for a single user end to end. Later milestones add the new features and get it ready for other people.

## Milestone 1: The current agent, as a cloud app (single user)

> Cross-cutting progress: `store/` is a DynamoDB single-table repository (keys per
> design.md, tenant isolation enforced per `user_id`, Decimal/float round-trip,
> account deletion) covered by moto tests. `api/app.py` is the HTTP API handler
> (session cookie + CSRF check, routes for me/applications/analytics/scans/
> deadlines, cross-tenant access blocked) also moto-tested. Service-dependent
> Lambda entry points (ingest, classify, excel, prep, notify, reminders) exist as
> documented stubs that raise until their Graph/Bedrock/SES client lands, so the
> CDK asset paths resolve. Backend: 113 tests, ruff + mypy --strict clean.

- [x] 1. Set up the repository and tooling
  - Create the folder layout from `.kiro/steering/structure.md`; `uv` project in `backend/` (ruff, mypy strict, pytest, moto); CDK TypeScript app in `infra/`; Vite React TS app in `web/`.
  - Add `.gitignore` entries for `reference/*.xlsx`, `.env*`, `cdk.out/`, `node_modules/`, `.venv/`.
  - GitHub Actions: lint, type-check and test backend + web; `cdk synth` on every PR.
  - _Requirements: 15_

- [x] 2. Domain models and enums
  - In `backend/domain/`: Pydantic models for User, Application, Event, Deadline, PrepPack, ScanRun; enums for Status, FurthestStage (ordered), FirmType, Programme, EmailType exactly as in the requirements glossary.
  - `firm_directory.yaml` seeded with every firm in `reference/agent_rules.md` plus common UK graduate employers; loader with alias lookup.
  - Unit tests for stage ordering and directory lookup.
  - _Requirements: 4.4, 5.1, 5.4_

- [x] 3. Core infrastructure (CDK)
  - DONE: `infra/` composes area constructs (`data`, `auth`, `web`, `notify`, `scan`, `api`) into one `AppStack` per stage. DynamoDB `JobTracker` with GSI1/GSI2, PITR and a stream; KMS token key (decrypt granted only to api/ingest/excel); Secrets Manager entry (MS client secret + generated session signing key); SQS scan + prep queues with DLQs; HTTP API with a catch-all route + CORS; Step Functions ScanWorkflow; EventBridge reminder rule; DynamoDB-stream + SQS event sources; CloudFront + S3 web hosting; 30-day log groups; X-Ray tracing. Both stages synth clean (81 resources each), SES policy scoped by from-address.
  - TODO before deploy: Lambda dependency packaging (layer or bundled asset), scope `bedrock:InvokeModel` to model ARNs, WAF (task 17), custom domain + ACM cert.
  - _Requirements: 14.3, 15.3_

- [ ] 4. Microsoft sign-in
  - Register the Entra app (`AzureADandPersonalMicrosoftAccount`, redirect URIs for dev/prod) and document the steps in README.
  - Implement `/api/auth/login`, `/api/auth/callback`, `/api/auth/logout` with MSAL (PKCE, state, nonce), KMS-encrypted refresh token, signed session cookie.
  - `integrations/graph_client.py`: get access token from stored refresh token, save rotated token, retry on 429/503 with `Retry-After`.
  - Tests: callback happy path, declined scopes, revoked token → `needs_reconnect`.
  - _Requirements: 1.1, 1.2, 1.3, 1.5, 1.6_

- [ ] 5. Mail ingestion and prefilter
  - DONE: `agent/ingest/prefilter.py` (ATS domains, keyword regex, blocklist, OTP/admissions rejects, per-user known + negative senders) with tests.
  - TODO: `agent/ingest/delta.py` (Graph delta sync, backfill, dedupe — needs Graph), the no-PATCH/no-move assertion test, body stripping + truncation.
  - `agent/ingest/delta.py`: per-folder delta sync (Inbox, Sent Items, user-chosen folders) with backfill start, saved delta links, one-day overlap, `ProcessedMessage` dedupe.
  - `agent/ingest/prefilter.py`: ATS domain list, keyword regex, blocklist, per-user negative senders.
  - Fetch full body only for prefilter passes; strip signatures/quotes; truncate to 4,000 chars; never persist.
  - Tests with recorded anonymised Graph responses; a test that asserts no message is ever PATCHed/moved.
  - _Requirements: 2.1-2.5, 3.1, 14.1_

- [ ] 6. Email classification with Bedrock
  - DONE: `agent/classify/deadline.py` (relative-deadline resolution: "within N days/hours", "by midnight Monday", "by Friday", end-of-day; resolved from email time + user tz, returned as UTC) with tests.
  - TODO: `integrations/bedrock.py` (Converse, tool use), the `agent/classify` prompt + schema-validation/retry/fallback (needs Bedrock), `tests/eval/` with ≥150 labelled emails.
  - `integrations/bedrock.py` (Converse API, tool use, model ID from config, token accounting).
  - `agent/classify/`: system prompt v1 from `reference/agent_rules.md` + few-shot examples; `EmailFacts` schema; retry once on validation error; fallback to Check email; confidence threshold.
  - Relative deadline resolution ("within five days of this email", "by midnight Monday") in code, using the email's received time and the user's time zone.
  - Build `tests/eval/` with ≥ 150 anonymised labelled emails and an eval script that reports precision/recall/status accuracy per prompt version; wire into CI with the thresholds.
  - _Requirements: 3.2-3.6, 8.1, 8.2, 15.4_

- [ ] 7. Matching and the status state machine
  - DONE: `state_machine.py` (`apply_event` + `apply_patch`), table-driven tests over every event type plus older-event, manual-edit, Optiver reopen, Maven and Deutsche Bank cases. `normalise.py` (company + role normalisation, token-set ratio). `matcher.py` (requisition ID → conversation → company+role similarity → single open app → new) with tests.
  - TODO: firm-type model fallback (needs Bedrock), timeline event construction with the Graph web link (needs ingest wiring).
  - Firm type resolution: directory → user override → cached model guess with `Unconfirmed` below 0.7.
  - Notes, next step and timeline event with email web link.
  - _Requirements: 4.1-4.8, 5.1-5.4_

- [ ] 8. Excel export to OneDrive (parity with today's tracker)
  - DONE: `builder.py` (Applications table, Summary formulas, Priorities, Scan log, Email link + hidden App ID columns, drop-downs, colour coding, 21-day amber flag). `importer.py` (reads edits back by header name + hidden App ID, diffs Status/Firm type/Programme/Next step/Notes, reads Priorities Done?/Manual rows, flags unknown values). Builder + importer round-trip tests.
  - TODO: `integrations/graph_onedrive.py` (eTag import-then-overwrite, 412/423 — needs Graph), parity test against the real `reference/Job_Applications_Tracker.xlsx`.
  - `importer.py`: read edits by header name and App ID; apply as manual edits; read Priorities Done? and Manual rows.
  - `integrations/graph_onedrive.py`: get metadata/eTag, import-then-overwrite flow, 412/423 handling.
  - Parity test: import the reference workbook → export → same rows, statuses and Summary counts.
  - _Requirements: 6.1-6.5, 13.1_

- [ ] 9. Scan workflow, schedules and scan report
  - DONE: the CDK `ScanWorkflow` (ingest → classify Map → match → excel → notify, task 3); `agent/start_scan.py` consumes the SQS queue and starts the workflow (moto-tested); `agent/match/handler.py` wires matcher + state machine + repo end to end (moto-tested); `agent/prep/router.py` enqueues prep-pack work on the stream transition into Interview (moto-tested); `api/notify.py` short-circuits when nothing changed.
  - TODO: per-user lock item on start_scan, EventBridge Scheduler create/update/delete + 6/day Scan-now limit, the SES scan-report body (needs SES).
  - EventBridge Scheduler: create/update/delete a per-user schedule (default every 2 days at a random time 07:00-09:00 local); `POST /api/scans` for Scan now with a 6/day limit.
  - SES scan report email in the same shape as today's message (X new, Y changes, new apps, status changes, To do); no email when nothing changed.
  - **Milestone check:** run for your own account and compare against your current tracker.
  - _Requirements: 7.1-7.5_

## Milestone 2: New features

- [ ] 10. Deadlines and reminders
  - Create/close Deadline items from events (assessment_invite, interview_invite, assessment_completed); precompute `remind_at` (48h before, 08:00 on the day) into GSI1 buckets.
  - `reminder_sweeper` Lambda every 15 min, grouped SES email per user, idempotent sent markers; overdue state in the API.
  - `GET/PATCH /api/deadlines`.
  - _Requirements: 8.1-8.5_

- [ ] 11. Outlook calendar sync
  - `integrations/graph_calendar.py`: create/update/delete events tagged with a single-value extended property; all-day vs timed rules; interview events with location/link.
  - Hooks from deadline and interview changes; bulk remove on opt-out or account deletion.
  - Test that only tagged events are ever modified.
  - _Requirements: 9.1-9.4_

- [ ] 12. Interview prep packs
  - DynamoDB stream → prep queue when furthest stage reaches Interview or later.
  - `agent/prep/`: `PrepPack` schema, prompt with role focus (quant/trading adds maths, probability and mental-maths questions), source tagging, no unsupported specific facts; user practice link.
  - API to view/regenerate/add notes; PDF export (print CSS in v1).
  - _Requirements: 10.1-10.5_

- [ ] 13. Analytics
  - DONE: `api/analytics.py` — `summary_counts()` (shared with the Excel Summary), `funnel()` by furthest stage with conversion rates, `firm_type_breakdown()`, `gone_quiet_share()`, `applications_per_week()`; test asserts counts equal the Excel COUNTIF logic.
  - TODO: response-time medians by firm type, per-user DynamoDB cache invalidated on scan/edit, wiring to the API route.
  - _Requirements: 11.1-11.5_

## Milestone 3: Web app

- [ ] 14. Frontend foundation and onboarding
  - Routing, typed API client, auth guard, layout; onboarding flow (privacy explainer → sign in → settings → optional import → first scan with live progress).
  - _Requirements: 1.4, 13.1-13.3, 14.5_

- [ ] 15. Dashboard and Applications pages
  - Dashboard: To do, recent changes, headline stats, Scan now.
  - Applications table with filters/search; detail drawer with timeline and email links; edit, manual add, merge, split, delete with undo; "not a job email".
  - _Requirements: 4.6, 4.7, 12.1-12.4_

- [ ] 16. Analytics, prep pack and settings pages
  - Recharts funnel, firm-type breakdown, response times, weekly volume with filters.
  - Prep pack page; Settings (schedule, reminders, calendar, OneDrive, export, delete account).
  - _Requirements: 10.4, 11.1-11.5, 14.4_

## Milestone 4: Ready for other people

- [ ] 17. Privacy, data rights and security hardening
  - Data export and account deletion (data, schedules, tokens, optional calendar cleanup) within 24h; log redaction tests; cross-tenant access tests on every route; WAF and rate limits; privacy policy and terms pages.
  - _Requirements: 14.1-14.7_

- [ ] 18. Reliability, cost controls and monitoring
  - Bounded concurrency for scans and Bedrock calls; per-user monthly cost cap; CloudWatch dashboard (scans, failures, tokens, cost, Graph throttles); alarms after 3 consecutive failures.
  - Load test: 200 simulated users scheduled at the same time.
  - _Requirements: 15.1-15.3_

- [ ] 19. Staging end-to-end test and launch checklist
  - Test Outlook.com account with seeded emails; Playwright E2E from onboarding to Excel in OneDrive.
  - Launch checklist from design.md: Microsoft publisher verification, SES production access + SPF/DKIM/DMARC, ICO fee check, Bedrock data terms, privacy policy live.
  - Invite 5-10 friends as beta users; review their Check email items and misclassifications to grow the eval set.
  - _Requirements: 14.5, 15.4_
