# Product: Job Application Tracker Agent

## What it is
A web app that connects to a job seeker's Outlook mailbox (read-only), finds every email about their job and internship applications, and keeps an always-up-to-date tracker of every application and its status. It tells them what they need to do next (assessments, interviews, deadlines) and how their search is going.

It started as a personal agent built for one graduate job seeker in London (finance, trading, quant, consulting roles) and is now being turned into a product other people can sign up for.

## Who it's for
- Students and recent graduates applying to many graduate schemes and internships at once (typically 20-100 applications per season).
- Heavy use of applicant tracking systems (Workday, Greenhouse, Ashby, Oracle Taleo / tal.net, SuccessFactors / jobs2web), job boards (LinkedIn, Bright Network, GRB, Totaljobs) and headhunters (e.g. Dartmouth Partners).
- v1 users have an Outlook mailbox (personal Outlook.com/Hotmail/Live or work/school Microsoft 365). Gmail comes later.

## Core value
1. **Never lose track:** one row per application with company, firm type, role, programme, date applied, furthest stage, status, last update, next step.
2. **Never miss a deadline:** assessment and interview deadlines are pulled from emails, put in the calendar and reminded.
3. **Show up prepared:** an interview prep pack is ready as soon as an interview invite lands.
4. **Learn from the search:** analytics show where applications convert and where they stall.
5. **Excel stays first-class:** users keep an Excel tracker in their OneDrive that the agent updates, in the same format the original agent used.

## Principles
- **Read-only on email.** The agent never sends, replies to, deletes, moves, flags or marks emails. The only write scopes are the user's calendar (for deadlines/interviews) and one OneDrive folder (for the Excel file).
- **Minimise data.** Store extracted facts (company, role, status, dates, short note) and message IDs, not email bodies.
- **Explainable.** Every status change links back to the email that caused it, so users can check it.
- **User is in charge.** Manual edits beat automatic ones unless a newer email arrives.
- **Don't guess.** If the firm type or the outcome isn't clear, say so ("Unconfirmed", "Check email") instead of inventing it.

## Out of scope for v1
Gmail, follow-up email drafts, weekly digest email, opportunities pipeline from job alerts, contacts tracker, mobile app, team/recruiter features. Keep the design open to them.
