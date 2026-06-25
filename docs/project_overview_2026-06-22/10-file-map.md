# File Map

## Root-Level Project Files

| Path | Role |
| --- | --- |
| `AGENTS.md` | Project agent rules and guardrails. |
| `README.md` | Sanitized source-of-truth repo README. |
| `README_AIS_ETR_MVP.md` | Main technical MVP README. |
| `AIS_ETR_PROJECT_OVERVIEW.md` | Older detailed overview, useful history but not current snapshot. |
| `CUSTOMER_PROJECT_BRIEF_TH.md` | Customer-facing brief, shell display may show Thai mojibake. |
| `render.yaml` | Render cloud blueprint for API, web, Postgres. |

## Core Python Package

| Path | Role |
| --- | --- |
| `ais_etr/cli.py` | Command registry. |
| `ais_etr/config.py` | Environment/settings. |
| `ais_etr/db.py` | SQLite schema and runtime DB access. |
| `ais_etr/pipeline.py` | Webex/replay/planned outage orchestration. |
| `ais_etr/parser.py` | Webex outage parser. |
| `ais_etr/matcher.py` | AIS protection hierarchy matcher. |
| `ais_etr/model.py` | Quantile baseline training/prediction. |
| `ais_etr/notifier.py` | Shadow payload and mock webhook sender. |
| `ais_etr/notification_policy.py` | Customer-facing gate for shadow payloads. |
| `ais_etr/ais_inbound.py` | AIS inbound verification API and local processor. |
| `ais_etr/ais_truth.py` | AIS truth import and shadow matching. |
| `ais_etr/ais_add_field_truth.py` | AIS Add Field truth candidate import. |
| `ais_etr/confidence_gate.py` | Green/amber/red/monitor eligibility. |
| `ais_etr/data_integrity.py` | Truth/context governance. |
| `ais_etr/production_path.py` | Sanitized export and production readiness gate. |
| `ais_etr/cloud_production.py` | Cloud gate packets, green reports, worker/daily QA. |
| `ais_etr/shadow_operations.py` | Daily reports, owner queues, console/mock report generation. |
| `ais_etr/webex.py` | Webex OAuth/client. |
| `ais_etr/webex_export.py` | Sanitized Webex history export. |
| `ais_etr/webex_audit.py` | Redacted Webex runtime audit. |
| `ais_etr/source_trace.py` | ArcGIS source tracing for no-match candidates. |
| `ais_etr/trace_audit.py` | Upstream trace audit. |
| `ais_etr/truth_quality.py` | Truth quality and model gate metrics. |

## Production-Path Apps

| Path | Role |
| --- | --- |
| `apps/api-go/` | Go API package. |
| `apps/api-go/internal/api/server.go` | HTTP handlers. |
| `apps/api-go/internal/storage/postgres.go` | Postgres persistence. |
| `apps/api-go/internal/sendcontrol/sendcontrol.go` | Production send decision policy. |
| `apps/api-go/internal/storage/migrations/` | Postgres migrations. |
| `apps/web-next/` | Next.js operator/demo console. |
| `apps/web-next/app/page.tsx` | Server page loading live or demo data. |
| `apps/web-next/app/mission-control.tsx` | Main console UI. |
| `apps/web-next/app/api/requests/route.ts` | API proxy/helper route. |

## Runtime Evidence

| Path | Role |
| --- | --- |
| `runtime/ais_etr.sqlite` | Local SQLite runtime state. |
| `runtime/model_quantiles.json` | Current model artifact. |
| `runtime/green_gate_tracker.md` | Green subset production gate tracker. |
| `runtime/production_path_readiness_gate.md` | Production-path readiness decision. |
| `runtime/ais_inbound_real_hit_status.json` | Latest local inbound real-hit aggregate. |
| `runtime/production_cloud_real_hit_status.json` | Latest cloud API aggregate. |
| `runtime/cloud_pilot/` | Cloud pilot package, runbooks, owner packets, daily QA. |
| `runtime/cloud_pilot/mvp_daily_qa_report.md` | Daily cloud/pilot QA summary. |
| `runtime/cloud_pilot/production_gate_owner_packet.md` | Owner-facing production gate packet. |
| `runtime/ais_mapping_repair_queue.md` | AIS mapping repair queue. |
| `runtime/webex_only_monitoring.md` | Webex-only monitoring report. |
| `runtime/shadow_send_eligibility.md` | Shadow send eligibility gate. |
| `runtime/notification_time_readiness.md` | Notification timing readiness. |

## Data Files

| Path | Role |
| --- | --- |
| `upstream_result.xlsx` | AIS upstream trace registry. |
| `ETR_PKN_2024.xlsx` | Historical ETR 2024. |
| `ETR_PKN_2025.xlsx` | Historical ETR 2025. |
| `ETR_PKN_2026_6M.xlsx` | Historical ETR 2026 first half. |
| `Event_from_report52_PKN.xlsx` | Event report export. |
| `gis_distance.csv` | GIS distance features. |
| `data/webex_shadow_samples.jsonl` | Parser sample corpus. |
| `data/webex_shadow_samples_real.jsonl` | Real/sanitized Webex sample lane if maintained. |
| `PEA_ReportPO_planned_outage_transformer_2026_complete.csv` | Planned outage source. |
| `AC_MAIN_FAIL_add_field.xlsx` | AIS AC main fail/add-field truth candidate source. |

## Tests And CI

| Path | Role |
| --- | --- |
| `tests/` | Python tests for parser, matcher, pipeline, gates, reports, cloud path. |
| `.github/workflows/production-cloud-ci.yml` | CI for Python guardrails, Go API, Next console. |

## Generated/Do-Not-Use-As-Source Areas

| Path | Note |
| --- | --- |
| `apps/web-next/.next/` | Generated Next build output. |
| `apps/web-next/node_modules/` or standalone node modules | Dependencies/build output. |
| `runtime/*browser_profile*` | Browser profiles/cache; exclude from review. |
| `runtime/private/` | Private/sensitive runtime files. |
| `runtime/*.jsonl` | May contain request/log evidence; use redacted summaries. |
| raw `.env` and token files | Do not read/share unless explicitly required for secure local config work. |

