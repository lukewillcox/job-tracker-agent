# Tech stack and conventions

## Cloud: AWS (region eu-west-2, London)
- **Infrastructure as code:** AWS CDK v2 in TypeScript. Everything is deployed from `infra/`. Separate `dev` and `prod` stages.
- **Compute:** AWS Lambda (Python 3.12) for the API and the scan pipeline. Step Functions orchestrates a scan for one user.
- **Scheduling:** EventBridge Scheduler, one schedule per user (default every 2 days at a randomised minute between 07:00 and 09:00 user local time) plus on-demand scans.
- **Queue:** SQS between the scheduler and scan workers so many users don't hit Graph and Bedrock at the same moment.
- **Database:** DynamoDB, single-table design (see design.md). Point-in-time recovery on.
- **Secrets:** Microsoft refresh tokens encrypted with a customer-managed KMS key before being stored. App secrets in AWS Secrets Manager.
- **Email out (reminders only):** Amazon SES from the app's own domain. Never from the user's mailbox.
- **Frontend hosting:** AWS Amplify Hosting (or S3 + CloudFront) for the web app.
- **Observability:** CloudWatch logs (no email content or tokens in logs), metrics, alarms; AWS X-Ray tracing on Lambdas.

## AI
- **Amazon Bedrock with Anthropic Claude models.** Model IDs come from configuration (`CLASSIFIER_MODEL_ID`, `PREP_MODEL_ID`), never hard-coded. Use a smaller, cheaper Claude model for email classification and a larger one for interview prep packs.
- Use **tool use / JSON schema output** for every extraction so results validate against Pydantic models. Reject and retry once on schema failure, then mark the email "Check email".
- Prompts live in `backend/agent/prompts/` as versioned files; log the prompt version with each classification.
- Only send the model what it needs: sender, subject, date, and the first ~4,000 characters of plain-text body with signatures and quoted replies stripped.

## Microsoft
- **Microsoft identity platform (Entra ID) app registration**, `signInAudience = AzureADandPersonalMicrosoftAccount` so both personal Outlook.com and work/school accounts can sign in.
- OAuth 2.0 authorization code flow with PKCE, confidential client on the backend (MSAL for Python).
- Delegated scopes: `openid profile email offline_access User.Read Mail.Read Calendars.ReadWrite Files.ReadWrite`. Never request `Mail.ReadWrite` or `Mail.Send`.
- **Microsoft Graph v1.0** for mail (delta queries), calendar events and OneDrive files. Respect `Retry-After` on 429/503.

## Backend code (Python)
- Python 3.12, `uv` for dependencies, `ruff` + `mypy --strict`, `pytest` with `moto` for AWS mocks and recorded Graph fixtures (anonymised).
- Pydantic v2 models for every entity and every LLM output.
- `openpyxl` for Excel generation and reading user edits back.
- Lambda Powertools for logging, tracing, idempotency.

## Frontend
- React + TypeScript + Vite, Tailwind CSS, TanStack Query, Recharts for analytics.
- Auth: session cookie (httpOnly, Secure, SameSite=Lax) issued by the backend after Microsoft sign-in.

## Rules
- No email bodies or tokens in logs, analytics events or error reports.
- All timestamps stored in UTC ISO 8601; display in the user's time zone (default Europe/London).
- Dates shown to users as DD/MM/YYYY.
- Every external call (Graph, Bedrock, SES) wrapped with retries, timeouts and idempotency keys.
