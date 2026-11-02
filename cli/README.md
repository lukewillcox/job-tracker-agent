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
3. schedule an automatic scan (every 2 days by default)
4. run your first scan

## Commands

- `jobtracker scan` — scan now and update the tracker
- `jobtracker status` — summary + your "beer tab" (what your scans cost the host)
- `jobtracker uninstall` — remove the schedule, local data and Keychain secrets

Your tracker is written to `~/.jobtracker/Job_Applications_Tracker.xlsx`.

## Privacy

Email bodies never leave your machine except the stripped text sent to the
classify API for the duration of one call — it is never stored or logged there.
Only extracted facts (company, role, status, dates) are kept locally.
