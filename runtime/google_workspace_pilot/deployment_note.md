# Google Workspace Pilot Deployment Note

Generated: `2026-06-21`

## Native Google Sheets Template

Title:

```text
PEA API Intellisense - Google Workspace Zero-Cost Pilot
```

Link:

```text
https://docs.google.com/spreadsheets/d/1ZSCoEKuSUYnuVT4-hVirprJqlsZWeNekuG-SnCSCuIk
```

Spreadsheet ID:

```text
1ZSCoEKuSUYnuVT4-hVirprJqlsZWeNekuG-SnCSCuIk
```

## Status

- Sheet imported as native Google Sheets: `yes`
- Apps Script code generated: `runtime/google_workspace_pilot/Code.gs`
- Web App deployment: `manual step pending`
- Mode: `shadow`
- Production send: `blocked`

## Next Manual Step

Open the Google Sheet, then:

1. Extensions > Apps Script
2. Paste `Code.gs`
3. Run `setupPilotSheets`
4. Set `pilot_key_sha256`
5. Deploy as Web App

Do not paste the raw pilot key into this file or any public artifact.
