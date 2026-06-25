# PEA API Intellisense / AIS ETR Project Handbook

Generated: 2026-06-22, Asia/Bangkok  
Workspace: `D:\PEA Intellisense data`  
Audience: owner/developer/operator กลับมาอ่านทบทวนเร็ว โดยไม่ต้องไล่ repo ทั้งหมด

## Current Truth

- Project mode: `shadow`
- Production send: `blocked`
- Customer-facing Auto ETR: not approved
- AIS outage/restore remains customer-facing truth
- Webex is trigger/device evidence only
- PEA/SFSD/ReportPO remains context or quarantine unless owner-approved

## Current Evidence Snapshot

Source of this snapshot: `python -m ais_etr summary`, `python -m ais_etr validate-env`, `python -m ais_etr sample-eval`, direct aggregate SQLite reads, current runtime reports.

| Area | Current value |
| --- | ---: |
| AIS registry assets in SQLite | 390 |
| Confidence-eligible AIS assets | 271 |
| `NO_METER` backlog | 119 |
| Runtime Webex messages | 500 |
| Current parsed outage events | 500 |
| Prediction rows | 2,500 |
| Notification rows | 2,510 |
| AIS inbound requests in SQLite | 35 |
| AIS inbound non-smoke requests | 4 |
| Cloud requests in Render/Postgres report | 5 |
| Cloud non-smoke requests | 0 |
| Green auto ETR rows | 0 / 30 |
| Current baseline q50 MAE | 19.82 min |
| Current baseline q10-q90 coverage | 0.754 |

Important caveat: `predictions` and `notifications` contain historical/replay rows whose `event_id` no longer joins to the current `outage_events` table. Use joined counts for current event analysis and append-only counts for audit history.

## Reading Order

1. [Executive Summary](01-executive-summary.md)
2. [Architecture And Flows](02-architecture-and-flows.md)
3. [Data Sources And Runtime](03-data-sources-and-runtime.md)
4. [Model, Evaluation, And Truth](04-model-evaluation-and-truth.md)
5. [Operations And CLI](05-operations-and-cli.md)
6. [Cloud And AIS Inbound API](06-cloud-and-ais-inbound-api.md)
7. [Guardrails And Governance](07-guardrails-and-governance.md)
8. [Testing And Quality](08-testing-and-quality.md)
9. [Open Questions And Next Steps](09-open-questions-and-next-steps.md)
10. [File Map](10-file-map.md)

## What This Handbook Does Not Include

- No API keys, tokens, room ids, DB URLs, or secrets.
- No raw Webex text.
- No full meter numbers, PEANO lists, or customer identity.
- No approval to enable production Auto ETR.

