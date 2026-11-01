# Requirements Document

## Introduction

The Job Application Tracker Agent connects to a user's Outlook mailbox with read-only access, finds emails about their job and internship applications, and maintains a tracker of every application and its status. It turns the personal agent that already works for one user into a multi-user web app on AWS.

**Parity with the existing agent (must keep):** read the mailbox, recognise application confirmations, assessment invites, interview invites, rejections, offers and "role closed" notices; create and update an Excel tracker with the same columns, statuses, firm types, Summary sheet and Scan log; run automatically every other day and on demand; report what changed.

**New in v1:** multi-user sign-up, deadline extraction and reminders, Outlook calendar sync, interview prep packs, analytics dashboard, a web dashboard for viewing and editing applications.

**Not in v1:** Gmail, follow-up drafts, weekly digest, opportunities pipeline from job alerts, contacts tracker.

### Glossary
- **Application:** one candidacy for one role at one company (two roles at the same company are two applications).
- **Event:** a fact extracted from one email about one application (e.g. "invited to SHL assessment on 28/10").
- **Status:** one of `Awaiting response`, `Assessment stage`, `Interview`, `Offer`, `Rejected`, `Closed`, `Closed by employer`, `No response`, `Not submitted`, `Check email`.
- **Furthest stage:** furthest point reached, never moves backwards: `Started` < `Applied` < `Eligibility check passed` < `Online assessment` < `Video interview` < `Interview` < `Assessment centre` < `Final round` < `Offer`.
- **Firm type:** one of `Investment bank`, `Boutique investment bank`, `Hedge fund`, `Trading firm`, `Private equity / credit`, `Asset manager`, `Fintech`, `Financial data`, `Energy & commodities`, `Professional services`, `Consulting`, `Tech`, `Other`, `Unconfirmed`.
- **Programme:** `Graduate`, `Internship`, `Experienced hire`, `Not stated`.
- **Scan:** one run of the agent over a user's mailbox for a time window.

## Requirements

### Requirement 1: Sign up and connect Outlook

**User Story:** As a job seeker, I want to sign in with my Microsoft account and connect my Outlook, so that the agent can read my application emails without me sharing a password.

#### Acceptance Criteria
1. WHEN a visitor clicks "Sign in with Microsoft" THEN the system SHALL start an OAuth 2.0 authorization code flow with PKCE that accepts both personal Microsoft accounts (Outlook.com, Hotmail, Live) and work/school accounts.
2. WHEN the consent screen is shown THEN the system SHALL request only `openid profile email offline_access User.Read Mail.Read Calendars.ReadWrite Files.ReadWrite`.
3. WHEN sign-in succeeds THEN the system SHALL create the user record, store the refresh token encrypted with a KMS key, and start onboarding.
4. WHEN onboarding runs THEN the system SHALL ask for: time zone (default Europe/London), how far back to scan the first time (default 3 months, max 12), whether to enable calendar sync, and whether to keep an Excel file in OneDrive (default on).
5. IF the user declines a scope THEN the system SHALL explain what stops working and let them continue with the features that remain possible.
6. WHEN the refresh token is revoked or expires THEN the system SHALL pause that user's scans, show a "Reconnect Outlook" banner, and email them once.

### Requirement 2: Read the mailbox (ingestion)

**User Story:** As a user, I want the agent to look through my inbox and sent mail, so that applications I made by email or through portals are all caught.

#### Acceptance Criteria
1. WHEN a user's first scan runs THEN the system SHALL read messages from Inbox, Sent Items and any folder the user marks as "job emails", received or sent within the chosen backfill window.
2. WHEN later scans run THEN the system SHALL fetch only messages that are new or changed since the previous scan, using Microsoft Graph delta queries, with a one-day overlap to avoid gaps.
3. WHEN the system reads a message THEN it SHALL fetch only sender, recipients, subject, received/sent time, conversation ID, internet message ID and body; and SHALL NOT change the message in any way (read state, flags, folders, categories).
4. WHEN a message is processed THEN the system SHALL record its ID so it is never classified twice, unless the user asks for a re-scan.
5. IF Graph returns 429 or 503 THEN the system SHALL wait for `Retry-After` and retry, and SHALL resume from the last saved delta token if the scan stops part-way.

### Requirement 3: Find and classify job emails

**User Story:** As a user, I want only real application emails picked up, so that job alerts, newsletters and spam don't clutter my tracker.

#### Acceptance Criteria
1. WHEN a message is ingested THEN the system SHALL first run a cheap prefilter (keywords such as application, applying, unfortunately, interview, assessment, candidate, offer, "next steps", and known applicant-tracking sender domains such as myworkday.com, greenhouse-mail.io, ashbyhq.com, tal.net, jobs2web.com, smartrecruiters.com, lever.co) and SHALL only send messages that pass to the AI model.
2. WHEN the model classifies a message THEN it SHALL return, against a strict schema: `is_job_application_email`, `email_type` (`confirmation`, `assessment_invite`, `interview_invite`, `rejection`, `offer`, `role_closed`, `incomplete_application_reminder`, `progress_update`, `other`), `company`, `role`, `programme`, `requisition_id`, `applied_via`, `deadline` (date-time or null), `deadline_text`, `interview_datetime`, `stage_reached`, `summary` (≤ 20 words) and `confidence` (0-1).
3. The system SHALL treat these as NOT application emails: university course admissions, event or careers-fair registrations, job alerts and "new jobs posted" emails, job-board marketing and premium offers, generic recruiter spam, newsletters, one-time passcodes and 2FA codes.
4. WHEN an email the user sent contains an application (e.g. a CV emailed to a recruiter) THEN the system SHALL treat it as a confirmation dated the sent date.
5. IF the model's confidence is below 0.6 OR the outcome is ambiguous THEN the system SHALL set the application's status to `Check email` and link the email.
6. IF the model output fails schema validation twice THEN the system SHALL record the email as `Check email` rather than drop it.

### Requirement 4: Match emails to applications and update status

**User Story:** As a user, I want each email attached to the right application with the right status, so that my tracker is accurate without manual work.

#### Acceptance Criteria
1. WHEN a classified email arrives THEN the system SHALL match it to an existing application by, in order: requisition ID, conversation ID, normalised company + role similarity, then normalised company alone if the user has only one open application there.
2. IF no application matches AND the email is a confirmation, assessment invite, interview invite, rejection, offer or role-closed notice THEN the system SHALL create a new application (date applied = confirmation date if known, otherwise `null` shown as "Not in emails").
3. WHEN an event is newer than the application's last update THEN the system SHALL update status using these rules: confirmation → `Awaiting response`; assessment invite → `Assessment stage`; interview invite → `Interview`; offer → `Offer`; rejection → `Rejected`; role closed → `Closed by employer`; incomplete-application reminder → `Not submitted`; assessment expired → `Closed`.
4. WHEN status changes THEN the system SHALL move furthest stage forward if the event shows a further stage and SHALL never move it backward.
5. WHEN an event is applied THEN the system SHALL set last update to the email date, set the next step (e.g. "Complete SHL assessment by 02/11"), and append a dated note (e.g. "28/10: invited to SHL online assessment").
6. IF the user has edited a field by hand THEN the system SHALL NOT overwrite that field unless a newer email than the manual edit changes it, and SHALL show that it changed.
7. WHEN an application in `Awaiting response` or `Assessment stage` has had no update for 21 days THEN the system SHALL flag it as "gone quiet"; after 60 days with no update it SHALL suggest `No response` (the user confirms).
8. Every status change SHALL keep a link to the email that caused it (open in Outlook on the web).

### Requirement 5: Firm type and programme

**User Story:** As a user, I want each application tagged by firm type and programme, so that I can see how I'm doing at banks vs. hedge funds vs. trading firms.

#### Acceptance Criteria
1. WHEN a new application is created THEN the system SHALL set firm type from a maintained firm directory (company name → firm type, aliases) if the company is listed.
2. IF the company is not in the directory THEN the system SHALL ask the model to choose a firm type from the allowed list with a confidence score, and SHALL use `Unconfirmed` when confidence is below 0.7.
3. WHEN a user changes a firm type THEN the system SHALL remember it for that company for that user.
4. The system SHALL set programme from the role title and email (e.g. "Graduate", "Internship", "Summer Analyst" → Internship), defaulting to `Not stated`.

### Requirement 6: Excel tracker in OneDrive

**User Story:** As a user, I want an Excel file that always reflects my tracker, so that I can keep working the way I do today.

#### Acceptance Criteria
1. WHEN OneDrive export is on THEN after each scan the system SHALL write `Job Search/Job_Applications_Tracker.xlsx` in the user's OneDrive.
2. The workbook SHALL have the same layout as the existing tracker:
   - **Applications** sheet, Excel table named `Applications`, columns: Company, Firm type, Role, Programme, Applied via, Date applied, Furthest stage, Status, Last update, Days since update, Next step, Notes; sorted newest first; frozen header; Arial 10; dates DD/MM/YYYY.
   - "Days since update" is the live formula `=IF(ISNUMBER(I{row}),TODAY()-I{row},"")`.
   - Drop-downs for Firm type, Programme and Status; status colour coding; amber highlight on Days since update ≥ 21 for active applications.
   - **Summary** sheet with live formulas: count by status, total, still active, breakdown by firm type (applications, still active, rejected/closed, got past application), count by programme, notes.
   - **Scan log** sheet: scan date, emails searched from, new applications added, status changes, notes.
   - **Priorities** sheet (already in the current tracker): Priority (`1 - Urgent`, `2 - High`, `3 - Medium`, `4 - Low`), Task, Company, Due date (date or "ASAP"), Days left (formula `=IF(ISNUMBER(D{row}),D{row}-TODAY(),"")`), Done? (Yes/No), Notes, Source (`Auto` or `Manual`). It is built from open deadlines, next steps and `Check email` items. Rows the user adds with Source `Manual`, and any Done? = Yes the user sets, SHALL be kept across exports.
   - New in v1: an extra Applications column **Email link**.
3. WHEN the system is about to overwrite the file AND the file was modified after the last export THEN the system SHALL first read Status, Firm type, Programme, Next step and Notes from it and apply any differences as manual edits (Requirement 4.6).
4. IF the file is locked or OneDrive is unavailable THEN the system SHALL retry later in the scan and SHALL show the file as "not updated" with the reason, and the web dashboard SHALL stay correct.
5. The user SHALL be able to download the same workbook from the web app at any time.

### Requirement 7: Scheduled and on-demand scans

**User Story:** As a user, I want scans to happen automatically and whenever I ask, so that the tracker is up to date without me thinking about it.

#### Acceptance Criteria
1. WHEN a user finishes onboarding THEN the system SHALL create a schedule to scan every 2 days at a random time between 07:00 and 09:00 local time; the user SHALL be able to change it to daily, every 2 days, weekly or off.
2. WHEN the user clicks "Scan now" THEN the system SHALL start a scan within 1 minute and show progress; the button SHALL be rate-limited to 6 per day per user.
3. WHEN a scan is already running for a user THEN the system SHALL NOT start a second one for that user.
4. WHEN a scan finishes THEN the system SHALL store a scan record (window, messages read, messages classified, new applications, status changes, errors, duration, model cost estimate).
5. WHEN a scan finds changes THEN the system SHALL notify the user by email (and in-app) with: "X new, Y status changes", the new applications (company – role – status), the status changes (company – old → new), and a "To do" list (upcoming deadlines, interviews, `Check email` items, applications that have gone quiet). WHEN a scan finds nothing THEN no email is sent.

### Requirement 8: Deadline extraction and reminders

**User Story:** As a user, I want to be reminded of assessment and interview deadlines, so that I never let one expire.

#### Acceptance Criteria
1. WHEN an email contains a deadline (explicit date, or a relative one such as "within 5 days of this email" or "by midnight Monday") THEN the system SHALL store a Deadline with application, what's due, due date-time in the user's time zone, the source email, and whether it was explicit or inferred.
2. WHEN a relative deadline is inferred THEN the system SHALL compute it from the email's received time and label it "estimated".
3. The system SHALL send reminders by email 48 hours before, and on the morning of, each open deadline (user can change both).
4. WHEN a later email shows the task was completed (e.g. "Thank you for completing our online assessment") THEN the system SHALL mark the deadline done and stop reminders; the user SHALL also be able to mark it done in the app.
5. WHEN a deadline passes without being marked done THEN the system SHALL show it as overdue and SHALL NOT change the application status until an email confirms the outcome.

### Requirement 9: Outlook calendar sync

**User Story:** As a user, I want interviews and deadlines in my calendar, so that they sit alongside the rest of my plans.

#### Acceptance Criteria
1. WHEN calendar sync is on AND a deadline is created THEN the system SHALL create an all-day (or timed, if a time is known) event in the user's default Outlook calendar titled "[Job] <Company> – <what's due>" with a reminder, and a link to the application in the body.
2. WHEN an interview time is known THEN the system SHALL create a timed event "[Job] <Company> interview" at that time, with the location or video link if given.
3. WHEN a deadline or interview changes or is cancelled THEN the system SHALL update or delete only the events it created (tracked by event ID and a custom extended property), never any other event.
4. WHEN calendar sync is turned off THEN the system SHALL offer to remove all events it created.

### Requirement 10: Interview prep pack

**User Story:** As a user, I want a prep pack ready when I get an interview, so that I can prepare quickly and well.

#### Acceptance Criteria
1. WHEN an application moves to `Interview`, `Assessment centre` or `Final round` THEN the system SHALL generate a prep pack within 15 minutes and notify the user.
2. The prep pack SHALL contain: firm overview (what they do, business lines, culture notes), what the role involves, the interview format if the email says it, 10-15 likely questions split into motivational, technical and (for quant/trading roles) maths, probability and mental-maths questions with model answer outlines, smart questions to ask the interviewer, and a checklist for the day.
3. The prep pack SHALL clearly label which facts come from the email and which are general knowledge that may be out of date, and SHALL NOT invent facts about the firm (recent deals, people, numbers) that it cannot back up.
4. The user SHALL be able to regenerate it, add notes to it, and export it to PDF.
5. The user SHALL be able to set a link to their own practice resources (e.g. a quant practice app) that appears in every prep pack.

### Requirement 11: Analytics dashboard

**User Story:** As a user, I want to see how my search is going, so that I can focus on what works.

#### Acceptance Criteria
1. The dashboard SHALL show: total applications, still active, rejected/closed, offers; a funnel (Applied → Assessment → Interview → Final → Offer) based on furthest stage; conversion rate at each step.
2. The dashboard SHALL break down applications, still-active and "got past application" rates by firm type, programme and applied-via channel.
3. The dashboard SHALL show response times (median days from application to first response, and to rejection) overall and by firm type.
4. The dashboard SHALL show applications per week over time and the share that have "gone quiet".
5. All charts SHALL be filterable by date range and firm type, and SHALL match the Excel Summary sheet's counts for the same data.

### Requirement 12: Applications view and manual editing

**User Story:** As a user, I want to see and edit my applications in the browser, so that I can fix mistakes and add applications that never sent an email.

#### Acceptance Criteria
1. The Applications page SHALL list all applications with the tracker columns, sortable and filterable by status, firm type, programme and date, with search.
2. Clicking an application SHALL show its timeline of events, each with the date, a one-line summary and a link to the email.
3. The user SHALL be able to edit any field, add an application manually, merge two applications that are the same, split a wrongly merged one, and delete an application (with undo for 30 days).
4. WHEN a user marks an email as "not a job email" THEN the system SHALL remove its events and use it as negative feedback for that sender in future scans.

### Requirement 13: Import an existing tracker

**User Story:** As an existing user of the personal agent, I want to bring my current spreadsheet in, so that I don't lose my history.

#### Acceptance Criteria
1. WHEN a user uploads an .xlsx in the existing tracker format THEN the system SHALL import every row as an application, keep the user's statuses and notes as manual values, and import the Scan log.
2. WHEN the first scan runs after an import THEN the system SHALL start from the last Scan log date (with one day of overlap) instead of the default backfill window.
3. IF the upload has unknown columns or values THEN the system SHALL show a preview with problems highlighted before importing.

### Requirement 14: Privacy, security and data rights

**User Story:** As a user trusting the app with my email, I want my data protected and under my control.

#### Acceptance Criteria
1. The system SHALL store only extracted fields, message IDs, a summary of at most 20 words and the email link; it SHALL NOT store email bodies or attachments beyond the processing step.
2. The system SHALL NOT send email content to any service other than Amazon Bedrock in the same AWS region, and SHALL keep Bedrock model invocation logging switched off so prompts and responses are not stored (confirm Bedrock's current data-use terms before launch).
3. All data SHALL be encrypted in transit (TLS 1.2+) and at rest (KMS); refresh tokens SHALL be encrypted with a dedicated key that only the scan and auth functions can use.
4. The user SHALL be able to export all their data (JSON + Excel) and delete their account; deletion SHALL remove all data, schedules and stored tokens within 24 hours, and offer to remove calendar events the app created.
5. The system SHALL show a privacy policy and terms before connecting, explaining what is read, what is stored, and for how long.
6. Logs, metrics and error reports SHALL contain no email content, subjects, addresses or tokens.
7. The system SHALL rate-limit and authenticate every API route, and each user SHALL only ever be able to read their own data (checked in tests).

### Requirement 15: Reliability and cost

**User Story:** As the operator, I want scans to be reliable and cheap, so that the app can serve many users.

#### Acceptance Criteria
1. A scan for a typical incremental window (≤ 500 new messages) SHALL finish within 5 minutes.
2. The prefilter SHALL keep at least 80% of non-job messages away from the model; the system SHALL track model tokens and estimated cost per user per scan, with a configurable monthly cap per user.
3. IF a scan fails THEN the system SHALL retry it up to 3 times with back-off, keep partial progress, and alert the operator after repeated failures.
4. Classification accuracy SHALL be measured against a labelled test set of at least 150 anonymised emails (including the categories in Requirement 3.3), with targets: ≥ 95% precision and ≥ 95% recall on "is a job application email", and ≥ 90% correct status.
