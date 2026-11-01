# Project structure

```
job-tracker-agent/
├── .kiro/
│   ├── steering/            # product.md, tech.md, structure.md (this file)
│   └── specs/
│       └── job-tracker-agent/
│           ├── requirements.md
│           ├── design.md
│           └── tasks.md
├── infra/                   # AWS CDK app (TypeScript)
│   ├── bin/app.ts
│   └── lib/                 # one construct per area: data, auth, api, scan, notify, web
├── backend/                 # Python 3.12
│   ├── api/                 # Lambda handlers for the HTTP API (auth, applications, analytics, settings, export)
│   ├── agent/               # the email agent
│   │   ├── ingest/          # Graph delta sync, prefilter
│   │   ├── classify/        # Bedrock classification + schema validation
│   │   ├── match/           # match emails to applications, status state machine
│   │   ├── prep/            # interview prep pack generation
│   │   └── prompts/         # versioned prompt files
│   ├── integrations/        # graph_mail.py, graph_calendar.py, graph_onedrive.py, ses.py, bedrock.py
│   ├── excel/               # workbook builder + edit importer (same format as the original tracker)
│   ├── domain/              # Pydantic models, enums (statuses, firm types, stages), firm directory
│   ├── store/               # DynamoDB repository layer
│   └── tests/               # unit, integration, fixtures/ (anonymised emails)
├── web/                     # React + Vite frontend
│   └── src/
│       ├── pages/           # Dashboard, Applications, ApplicationDetail, Analytics, Settings, Onboarding
│       ├── components/
│       └── api/             # typed API client
├── reference/               # the original personal tracker spec (columns, statuses, rules) for parity tests
└── README.md
```

## Naming
- Python: snake_case modules, PascalCase models. One Lambda handler per file, named `handler`.
- DynamoDB keys: `PK`/`SK` strings with `USER#`, `APP#`, `EVENT#`, `DEADLINE#`, `SCAN#`, `PREP#` prefixes.
- Enum values are the human-readable strings shown in the UI and Excel (e.g. `"Awaiting response"`), so exports need no mapping.
