# Job Application Tracker Agent

A web app that reads a job seeker's Outlook (read-only), tracks every application and its status, reminds them of deadlines, adds interviews to their calendar, prepares them for interviews, shows analytics, and keeps an Excel tracker in their OneDrive.

## Start here (in Kiro)
1. Open this folder in Kiro (File → Open Folder → `Documents/job-tracker-agent`).
2. Kiro picks up the steering files in `.kiro/steering/` automatically: what the product is, the tech stack and the folder layout.
3. Open the spec at `.kiro/specs/job-tracker-agent/`:
   - `requirements.md`: what it must do (user stories and acceptance criteria)
   - `design.md`: how it works on AWS (architecture, data model, pipeline)
   - `tasks.md`: the build plan, in order
4. Review and tweak `requirements.md` first, then `design.md`. Then in `tasks.md` click **Start task** on task 1 and work down. Milestone 1 (tasks 1-9) gets your current agent running in the cloud for your own account.

## Before you build (accounts you'll need)
- An **AWS account** with Amazon Bedrock enabled in eu-west-2 (London), and access granted to the Anthropic Claude models you'll use.
- A **Microsoft Entra app registration** (free, at entra.microsoft.com → App registrations). Set supported account types to "Accounts in any organizational directory and personal Microsoft accounts".
- A domain for sending reminder emails through Amazon SES.

## Reference
`reference/` holds the rules and Excel layout of the original personal agent, which the new app must match:
- `agent_rules.md`
- `build_tracker.py`
- `Job_Applications_Tracker.xlsx`: your real tracker, used for a parity test. **Never commit it.** It's in `.gitignore`.

## Keep private
A `.gitignore` is already set up so spreadsheets (your real data) and secrets (`.env` files) are never committed. Check it's still there before your first `git commit`.
