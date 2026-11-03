# Requirements Document: Prospects Agent

## Introduction

The Prospects agent finds new graduate jobs and internships that fit the user, once a week, and lists them on a new **Prospective roles** tab in the same Excel tracker. It searches the web from a short user **profile** (what they are looking for, degree, skills, target roles, locations). It works alongside the existing tracker agent: it never suggests a role the user has already applied for, and a prospect turns into **Applied** when the tracker sees the application confirmation.

It ships inside the existing `jobtracker` CLI, so friends get it when they install or update. Web search and AI ranking run through the existing classify API on Luke's AWS account, billed to the user's beer tab.

### Glossary
- **Profile:** the user's search preferences (see Requirement 1).
- **Programme type:** `Graduate`, `Internship` or `Both`.
- **Prospect:** one job found by the agent, not yet applied to.
- **Fit:** a 1-5 score of how well a prospect matches the profile, with a one-line reason.
- **Restricted site:** a site that needs a login or forbids automated access (LinkedIn, myUCLcareers / UCL careers portals, Handshake-style university portals). The agent stores links to these but never opens them.
- **Prospect status:** `New`, `Interested`, `Applied`, `Not for me`.

### Out of scope
Scraping Google or any job board; reading job alert emails; logging in to any site; applying on the user's behalf.

## Requirements

### Requirement 1: Profile

**User Story:** As a job seeker, I want to describe what I'm looking for once, so that the searches fit me.

#### Acceptance Criteria
1. WHEN the user runs `jobtracker setup` THEN the system SHALL ask for: programme type (Graduate / Internship / Both), start year, degree(s), skills, target roles, locations and exclusions, with sensible defaults and the option to skip.
2. WHEN the user runs `jobtracker profile` THEN the system SHALL show the current profile and let them edit any field, and `jobtracker profile --edit` SHALL open the profile file in the default editor.
3. The profile SHALL be stored locally in `~/.jobtracker/profile.json` and SHALL only be sent to the classify API inside a prospects request, never stored server-side.
4. IF no profile exists THEN the weekly prospects run SHALL be skipped with a one-line hint to run `jobtracker profile`.

### Requirement 2: Weekly search

**User Story:** As a job seeker, I want new matching roles found for me every week without me searching.

#### Acceptance Criteria
1. The system SHALL run the prospects search once a week via the existing launchd schedule, and on demand with `jobtracker prospects`.
2. WHEN a run starts THEN the system SHALL generate 4-6 web search queries from the profile using the classify API. Every query SHALL include the programme type wording ("graduate" / "internship" / "summer internship") and the start year, and at least one target role or skill.
3. The system SHALL run the queries with the Brave Search API. The Brave API key SHALL be held server-side (classify API), never in the CLI or the repo.
4. The system SHALL prefer recent results (the last 30 days where the search API supports a freshness filter).
5. The system SHALL enforce a per-user monthly query cap (default 40) server-side so total usage stays within the free search credit; WHEN the cap is reached THEN the run SHALL stop and say so.
6. Duplicate results (same URL, or same company + role) SHALL be merged.

### Requirement 3: Restricted sites

**User Story:** As a user, I want links to LinkedIn and university portals without the tool breaking their rules or needing my passwords.

#### Acceptance Criteria
1. The system SHALL NEVER fetch a URL on a restricted site. Restricted domains SHALL be a configurable list including linkedin.com and UCL / myUCLcareers domains.
2. WHEN a search result is on a restricted site THEN the system SHALL still add it as a prospect using only the result's title, snippet and URL, with Source set to the site name.
3. For other results, the system MAY fetch the page once, with a clear User-Agent, a 10-second timeout and no retries, only to fill in missing company, role, location or closing date.

### Requirement 4: Extraction and fit

**User Story:** As a job seeker, I want each role summarised and ranked so I see the best ones first.

#### Acceptance Criteria
1. For each result the system SHALL extract company, role, location, programme type and closing date (if stated), via the classify API.
2. The system SHALL score fit 1-5 against the profile with a one-line reason (e.g. "Python + stats match; 2027 graduate; London").
3. The system SHALL drop results with fit below 3, results whose programme type doesn't match the profile, results matching an exclusion, and pages that are not a job posting (news, blog posts, salary pages).
4. AI costs SHALL be recorded against the user's beer tab like classification.

### Requirement 5: Prospective roles tab

**User Story:** As a job seeker, I want the new roles in my tracker in the same style as the rest.

#### Acceptance Criteria
1. The workbook SHALL include a **Prospective roles** sheet after Priorities, in the house style (navy 1F3864 header, white bold Arial 11, Arial 10 body, thin D0D0D0 borders, frozen header).
2. Columns: Found, Company, Role, Programme, Location, Closing date, Fit, Why, Link, Source, Status.
3. Status SHALL be a dropdown (New / Interested / Applied / Not for me). Rows SHALL be sorted by Status (New and Interested first), then Fit (high first), then Closing date (soonest first).
4. Closing within 7 days SHALL be highlighted amber (FFE699) and past closing dates greyed; "Not for me" and "Applied" rows SHALL be greyed.
5. Link SHALL be a clickable hyperlink.
6. Prospects SHALL persist between runs in the local store; a weekly run adds new rows and never deletes existing ones. Prospects older than 60 days with status New SHALL be dropped.

### Requirement 6: Working with the tracker agent

**User Story:** As a job seeker, I want the two agents to stay in sync.

#### Acceptance Criteria
1. The system SHALL NOT add a prospect whose company + role matches an existing Applications row (same normalised company, fuzzy role match).
2. WHEN the tracker records an application that matches a prospect THEN the prospect's status SHALL become Applied.
3. WHEN the user sets a prospect to `Not for me` in Excel THEN that status SHALL be imported on the next run and the same role SHALL never be re-added.
4. User edits to Status in Excel SHALL be preserved across runs (same import pattern as Priorities).

### Requirement 7: Friends and privacy

1. The feature SHALL be part of the `jobtracker` CLI and SHALL work for every invited user with their own profile.
2. The classify API SHALL NOT log profile contents, queries or results; only username, counts and cost.
3. `jobtracker uninstall` SHALL remove the profile and stored prospects.
4. `jobtracker status` SHALL show the number of open prospects and when the last prospects run happened.
