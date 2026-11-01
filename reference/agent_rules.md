# Reference: how the current personal agent works (v0)

This is the behaviour the cloud version must match or improve on. It comes from the scheduled task that has been running against one real Outlook.com mailbox since October 2026.

## How v0 runs
- Every other day at 08:41 (Europe/London), plus on demand.
- Opens Outlook on the web in a browser and runs these searches: `application`, `applying`, `unfortunately`, `interview`, `assessment`, `candidate`, `offer`, `"next steps"`. It reads the result list (sender, subject, date, preview), and opens an email only when the preview is unclear.
- Window: from one day before the last Scan log date up to today.
- Updates `Documents/Job Search/Job_Applications_Tracker.xlsx` with openpyxl (makes a backup copy first), appends to Scan log, then sends a short report.
- Never sends, replies to, deletes, moves, flags or marks emails.

## Classification rules (keep)
**Count as application emails:** confirmations, assessment/test invites, interview invites, rejections, offers, "position filled/closed" notices, reminders to finish an application, CVs the user emailed to a recruiter (from Sent Items).

**Ignore:** university course admissions (e.g. UCL MSc), event/careers-fair registrations (e.g. BCG event), job alerts and "new jobs posted" emails (LinkedIn Job Alerts, careers.fitch.group), LinkedIn Premium and job-board marketing (Totaljobs "save time", GRB marketing), generic recruiter spam (sender "Recruiter" offering insurance/sales interviews), newsletters, 2FA/OTP codes, brokerage sign-ups.

**Unclear:** set status `Check email` (e.g. BlockTech 09/10 "Your Application at BlockTech", EY UK 02/10 "update on your application").

## Update rules (keep)
- Match to an existing row by company, and by role when a company has several rows (BNP Paribas Research vs Trading).
- Update a row only when the email is newer than its Last update.
- Furthest stage only moves forward.
- Append a dated note, e.g. `28/10: invited to SHL online assessment`.
- Leave hand-edited statuses alone unless a newer email arrives.
- New rows: firm type from knowledge or a web search, `Unconfirmed` rather than guess.

## Real cases worth turning into anonymised test fixtures
| Case | Lesson |
|---|---|
| Optiver: "graduation date does not meet eligibility" then "the earlier message was the result of an issue… application reopened" | A later correction must undo a rejection |
| Maven: progressed → assessment completed → rejected | Furthest stage stays at Online assessment after the rejection |
| Deutsche Bank: assessment invite then "Online Assessment Experience Expired" | Missed deadline becomes `Closed`. This is the case deadline reminders exist to prevent |
| Barclays: application received + SHL assessment within 5 days | Relative deadline must be resolved from the email date |
| ExxonMobil: behavioural assessment invite then a second Arctic Shores invite with a deadline | A second invite updates next step/deadline without a status change |
| Quantbot: confirmation without role, later email names the role | Role gets filled in later |
| Warburg Pincus / Fenchurch via dartmouthpartners.com | Sender is the headhunter, company is in the subject |
| Bloomberg forwarded from the user's own address | Forwarded emails in Sent Items still count |
| Taula Capital: CV emailed after a careers fair | Sent-mail applications count |
| SMBC via Bright Network "submit within 3 days" reminders | `Not submitted` |
| GRB "opportunity no longer available" with no employer named | `Closed by employer`, company unknown |
| EY Switzerland: rejected after interview due to visa sponsorship | Furthest stage Interview, status Rejected |
| Recruiter "Available for interview" spam | Not an application despite the word "interview" |
| UCL admissions "application submitted" | Not a job application |

## Firm types used so far
| Firm type | Companies |
|---|---|
| Investment bank | BNP Paribas, Santander CIB, Citi, Deutsche Bank, SMBC, Barclays |
| Boutique investment bank | Evercore, Lazard, Fenchurch Advisory, Augusta & Co |
| Hedge fund | Quantbot Technologies, Taula Capital, Squarepoint Capital |
| Trading firm | Maven Securities, BlockTech, Optiver, Jump Trading, Tower Research Capital, G-Research |
| Private equity / credit | Warburg Pincus, Rothschild & Co (Five Arrows) |
| Asset manager | Baillie Gifford, Macquarie (Asset Management) |
| Fintech | ION Group, Intropic, Monzo |
| Financial data | Bloomberg |
| Energy & commodities | Centrica, ExxonMobil |
| Professional services | PwC, EY |
| Tech | Bending Spoons |
| Unconfirmed | Circeus, Mondrian Alpha, ANL |

## Excel format
Sheets in the live workbook: **Applications**, **Priorities**, **Summary** and **Scan log**. `build_tracker.py` (example data only) builds Applications and Summary. Priorities was added later: Priority, Task, Company, Due date, Days left (formula), Done?, Notes, Source (Auto/Manual). The live workbook is `Job_Applications_Tracker.xlsx` in this folder. It contains real personal data, so it's git-ignored and must never be committed. Use it only for the local parity test.
