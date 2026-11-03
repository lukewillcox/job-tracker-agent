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
- An **AWS account** with Amazon Bedrock enabled in **eu-north-1 (Stockholm)**, and access granted to the Anthropic Claude models you'll use.
- A **Microsoft Entra app registration** (free, at entra.microsoft.com → App registrations). Set supported account types to "Accounts in any organizational directory and personal Microsoft accounts".
- A domain for sending reminder emails through Amazon SES.

### Enabling Bedrock models (eu-north-1)
1. AWS Console → **Bedrock** (region **Europe (Stockholm) eu-north-1**) → **Model access** → **Modify model access** → enable the Anthropic Claude models you want (a Haiku-class model for classification, a Sonnet-class model for prep packs) → Submit.
2. Get the exact callable inference-profile ids for your account/region (in eu-north-1, Claude models are generally invoked via an `eu.` regional inference profile, not the bare model id):
   ```bash
   aws bedrock list-inference-profiles --region eu-north-1 \
     --query "inferenceProfileSummaries[?contains(inferenceProfileId, 'anthropic')].[inferenceProfileId,inferenceProfileName]" \
     --output table
   ```
3. These ids are wired as the defaults in `infra/bin/app.ts` for eu-north-1
   (classifier = Claude Haiku 5.5, prep = Claude Sonnet 5.5), so a plain
   `cdk deploy` uses them. Override per stage/account if needed:
   ```bash
   cd infra && npx cdk deploy JobTracker-dev \
     -c classifierModelId=eu.anthropic.claude-haiku-5-5 \
     -c prepModelId=eu.anthropic.claude-sonnet-5-5
   ```

### Config defaults (overridable with `-c`)
`infra/bin/app.ts` ships working defaults so `cdk deploy JobTracker-dev` is
sign-in-ready with no extra flags:
- `msClientId` = the dev Entra app id; `msAuthority` = `.../common`.
- `MS_REDIRECT_URI` is **derived from the deployed HTTP API URL**, so the
  callback is correct on the first deploy (printed as the `MsRedirectUri` output).
- `sesFromAddress` = `luke.willcox@outlook.com` (verified in the SES sandbox;
  also the only allowed recipient there). The SES IAM policy is scoped to that
  one identity ARN. Switch to a real domain later with `-c sesFromAddress=...`.

### Setting the Microsoft client secret (after first deploy)
The stack creates the secret `job-tracker/dev/app` (in eu-north-1) with a generated session signing key and an empty `ms_client_secret` slot. Fill it in without sharing the value:
```bash
aws secretsmanager get-secret-value --region eu-north-1 \
  --secret-id job-tracker/dev/app --query SecretString --output text > /tmp/jt.json
# edit /tmp/jt.json: set "ms_client_secret", keep "session_signing_key"
aws secretsmanager put-secret-value --region eu-north-1 \
  --secret-id job-tracker/dev/app --secret-string file:///tmp/jt.json
rm /tmp/jt.json
```

### Deploy commands
```bash
export CDK_DEFAULT_REGION=eu-north-1   # matches the CDK default; set your profile too
cd infra && npm ci
bash scripts/build-layer.sh                        # build the Python deps layer first
npx cdk bootstrap aws://<account-id>/eu-north-1   # once per account+region
npx cdk synth
# defaults (model ids, MS client id/authority/redirect, SES sender) are baked in
npx cdk deploy JobTracker-dev
```
After deploy, read the stack outputs: register `MsRedirectUri` in the Entra app
(Authentication → Web → Redirect URIs), and set the Microsoft client secret in
Secrets Manager (above).

## Prospects agent (new roles, weekly)
The `jobtracker` CLI also finds new graduate jobs/internships from a short
search profile and lists them on a **Prospective roles** tab. Search + ranking
run on the shared classify API (`JobTrackerClassifyApi-*` stack), billed to the
user's beer tab like classification. See `cli/README.md` for the user-facing
steps.

Host setup (one-off): web search uses the **Brave Search API**. The key is held
server-side only — the stack creates an (empty) secret `jobtracker/brave-api-key-<stage>`
and the Lambda reads it at runtime; it is never in the CLI or the repo. After
deploying the classify API, set the real key (get a free one at
brave.com/search/api):
```bash
aws secretsmanager put-secret-value --region eu-north-1 \
  --secret-id jobtracker/brave-api-key-dev \
  --secret-string 'YOUR_BRAVE_KEY'          # or '{"brave_api_key":"..."}'
```
A per-user monthly query cap (default 40) keeps total usage inside the free
Brave credit.

## Reference
`reference/` holds the rules and Excel layout of the original personal agent, which the new app must match:
- `agent_rules.md`
- `build_tracker.py`
- `Job_Applications_Tracker.xlsx`: your real tracker, used for a parity test. **Never commit it.** It's in `.gitignore`.

## Keep private
A `.gitignore` is already set up so spreadsheets (your real data) and secrets (`.env` files) are never committed. Check it's still there before your first `git commit`.
