# jobtracker (local CLI)

Keeps an always-up-to-date tracker of your job applications by reading your
Outlook mailbox **read-only**, on **your** Mac. Classification runs on the
host's shared API (you just need an invite code), so you don't need your own AWS
or Bedrock account.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/lukewillcox/job-tracker-agent/main/install.sh | bash
```

Then follow the prompts, or run setup directly:

```bash
jobtracker setup --username <the-username-you-were-given>
```

Setup will:
1. ask you to paste your **invite code** (stored in the macOS Keychain)
2. sign you in to Microsoft via a device code (read-only mail access)
3. schedule an automatic scan (every 2 days by default) and a weekly search for
   new roles
4. (optional) ask a few questions to build your **search profile** — what
   you're looking for, so it can find new roles for you. Skippable; set it up
   anytime with `jobtracker profile --edit`.
5. run your first scan

## Commands

- `jobtracker scan` — scan now and update the tracker
- `jobtracker prospects` — find new roles that fit your profile and add them to
  the **Prospective roles** tab (runs weekly on its own too)
- `jobtracker profile` — show your search profile; `--edit` to change it
- `jobtracker status` — summary (incl. open prospects) + your "beer tab"
- `jobtracker uninstall` — remove the schedule, local data and Keychain secrets

Your tracker is written to `~/.jobtracker/Job_Applications_Tracker.xlsx`.

## Prospects (finding new roles)

Once you've set a search profile, the agent searches the web once a week for
new graduate jobs and internships that fit you, and lists them on a
**Prospective roles** tab with a 1-5 fit score and a one-line reason. It never
suggests a role you've already applied for, and a prospect flips to **Applied**
automatically when a scan sees your confirmation email. Set a row's **Status**
to `Not for me` in Excel and it won't come back. Links to sites that need a
login (LinkedIn, university portals) are listed but never opened.

## Privacy

Email bodies never leave your machine except the stripped text sent to the
classify API for the duration of one call — it is never stored or logged there.
Only extracted facts (company, role, status, dates) are kept locally.

Your search profile stays on your Mac (`~/.jobtracker/profile.json`). It is sent
to the API only inside a prospects request and is never stored server-side; the
API logs counts and cost only, never your profile, the search queries or the
results.
