# AIS ETR Automation MVP

This package implements the Windows pilot pipeline for AIS ETR shadow notifications.

## What It Does

1. Polls Webex messages using OAuth integration tokens or a bot token.
2. Parses outage device, feeder, district, and event time from the message text.
3. Loads the current AIS traced registry from `upstream_result.xlsx`.
4. Matches affected AIS meters by protection hierarchy: CB, Recloser, Switch, Transformer, then Feeder fallback.
5. Predicts ETR using a quantile baseline model that returns q10/q25/q50/q75/q90.
6. Sends only shadow-mode payloads to a mock webhook and records all runtime state in SQLite.
7. Reads planned outage ReportPO CSVs and sends AIS shadow notifications only for the configured pilot districts and minimum advance notice window.

The current environment does not include LightGBM or scikit-learn, so the model module uses a dependency-light quantile baseline. Its public prediction contract is intentionally the same shape expected from a future LightGBM quantile model.

## Setup

```powershell
python -m ais_etr setup-env
# Edit .env and add Webex OAuth or bot credentials plus optional AIS_MOCK_WEBHOOK_URL
python -m ais_etr validate-env
```

Use the bundled Python runtime in this Codex workspace, or any Python environment with `pandas` and `openpyxl`:

```powershell
python -m ais_etr init-db
python -m ais_etr build-registry
python -m ais_etr train
python -m ais_etr sample-eval
python -m ais_etr poll-once --max-messages 50
python -m ais_etr summary
```

For OAuth polling, set `WEBEX_AUTH_MODE=oauth`, `WEBEX_CLIENT_ID`, `WEBEX_CLIENT_SECRET`, `WEBEX_AUTHORIZATION_URL`, `WEBEX_REDIRECT_URI`, and `WEBEX_SCOPES`, then run:

```powershell
python -m ais_etr webex-auth
python -m ais_etr webex-rooms --query outage
```

After selecting the room, set `WEBEX_ROOM_ID` and run `python -m ais_etr poll-once --max-messages 10`.

For a bounded pilot polling run:

```powershell
python -m ais_etr poll-loop --interval-seconds 60 --iterations 10 --max-messages 50
```

To export historical Webex room messages for offline parser audit and training/test corpus preparation:

```powershell
python -m ais_etr webex-export-history --max-messages 500 --output runtime/webex_history_export.jsonl --csv-output runtime/webex_history_export.csv
```

The default export keeps message id, timestamps, text/markdown, parent id, and file count. It does not include the raw room id, sender identity, or full raw Webex JSON unless `--include-room-id`, `--include-actor`, or `--include-raw` is explicitly passed.

Replay exported history through the shadow parser, AIS protection matcher, and ETR predictor without posting to any webhook:

```powershell
python -m ais_etr webex-replay-history --source runtime/webex_history_export.jsonl --audit-output runtime/webex_history_replay_audit.csv
python -m ais_etr shadow-truth-infer-webex --output runtime/shadow_truth_mapping_webex_inferred.csv --candidates-output runtime/webex_truth_candidates.csv
python -m ais_etr shadow-report --truth-mapping runtime/shadow_truth_mapping_webex_inferred.csv --output runtime/shadow_evaluation_webex_inferred.csv
```

Replay records notification payloads in SQLite as `REPLAY_CAPTURED` shadow rows. It does not call the mock webhook or any AIS endpoint.

## LINE / LINE OpenChat Ingest

LINE group capture is shadow-only and uses the same parser/matcher/predictor replay path as Webex after sanitization.

For old LINE group history and LINE OpenChat, use an owner-approved manual export plus a consent manifest:

```powershell
python -m ais_etr line-import-history --source path\to\line_export.csv --manifest path\to\line_manifest.json --output runtime/line_history_normalized.jsonl
python -m ais_etr line-replay-history --source runtime/line_history_normalized.jsonl --audit-output runtime/line_history_replay_audit.csv
```

Manifest JSON must include `owner`, `source_type`, `date_range`, `consent_basis`, `allowed_use`, `retention`, `redaction_level`, and an approval flag such as `approved: true`. OpenChat imports must also be department-controlled; public/uncontrolled OpenChat exports are blocked as `blocked_needs_owner_approval`.

For new LINE group messages, configure an official LINE Messaging API channel and set:

```text
LINE_CHANNEL_SECRET=
LINE_ALLOWED_GROUP_IDS=
LINE_CAPTURE_MODE=shadow
```

Then run the local webhook receiver:

```powershell
python -m ais_etr line-webhook-server --host 127.0.0.1 --port 8091
```

The webhook verifies `X-Line-Signature`, accepts text message events only from allowlisted groups, stores hashed chat/sender ids, and writes sanitized JSONL. Do not use unofficial scraping or personal tokens.

For Render cloud capture, use the dedicated Python webhook service from `render.yaml`:

```text
https://pea-line-webhook.onrender.com/line/webhook
```

If Render assigns a different service URL, use that displayed URL plus `/line/webhook`. Render must have `LINE_CHANNEL_SECRET`, `LINE_ALLOWED_GROUP_IDS`, and `LINE_CAPTURE_MODE=shadow` configured before LINE webhook verification will pass. Health check path is `/health`; sanitized evidence is written to `runtime/line_webhook_capture.jsonl` and `runtime/line_webhook_capture.sqlite` inside the running service.

Operator setup checklist: `docs/line_render_setup.md`.

After replay, export no-match candidates for topology or registry repair:

```powershell
python -m ais_etr no-match-repair-candidates --output runtime/no_match_registry_repair_candidates.csv
python -m ais_etr trace-no-match-candidates --candidates runtime/no_match_registry_repair_candidates.csv --upstream upstream_result.xlsx --output runtime/no_match_upstream_trace_audit.csv --markdown-output runtime/no_match_upstream_trace_audit.md
```

This groups unmatched Webex events by protection device and feeder, adds current registry coverage counts, checks the current upstream trace workbook, and suggests the next repair action without exporting raw Webex text or PEANO lists.

For planned outage alerts, the default rule is AIS-only matches in `พังโคน`, `วาริชภูมิ`, and `นิคมน้ำอูน`, at least 3 days before `กำหนดการเริ่มดับไฟ`:

```powershell
python -m ais_etr planned-notify --now 2026-06-17T08:00:00
```

## AIS Inbound Verification API

AIS can initiate a shadow verification request when a site/meter detects AC main fail. This is a shadow-only API for confirming whether current PEA evidence supports a distribution-side outage.

Draft contract:

```text
runtime/ais_inbound_api_contract_draft.md
```

Create a sample request:

```powershell
python -m ais_etr ais-inbound-demo-request --output runtime/ais_inbound_demo_request.json --peano <PEANO>
```

Process one request offline without posting a callback:

```powershell
python -m ais_etr ais-inbound-verify-file --source runtime/ais_inbound_demo_request.json --no-callback-post
```

Run the local shadow API:

```powershell
python -m ais_etr ais-inbound-api --host 127.0.0.1 --port 8090 --no-callback-post
```

The API returns `202 RECEIVED`, writes private runtime audit rows, and captures a shadow callback payload. If `AIS_CALLBACK_URL` or `--callback-url` is configured, it can POST the callback to an AIS mock endpoint. It does not send production AIS ETR and does not update `runtime/model_quantiles.json`.

After shadow events have accumulated:

```powershell
python -m ais_etr shadow-report --output runtime/shadow_evaluation.csv
python -m ais_etr export-backlog --output runtime/no_meter_backlog.csv
```

## ReportPO ETR Truth Import

Use the ReportPO ETR tab as a downstream truth source when direct OMS/eRespond/DMS DB access is not available. The actual truth target is:

```text
actual_restoration_minutes = FIRST_RESTORE_TIME - EVENT_START_TIME
```

New ReportPO exports also write explicit truth columns:

```text
reportpo_first_restore_minutes = FIRST_RESTORE_TIME - EVENT_START_TIME
event_end_duration_minutes     = EVENT_END_TIME - EVENT_START_TIME
truth_source                   = reportpo
truth_target                   = reportpo_first_restore_minutes
truth_definition               = FIRST_RESTORE_TIME - EVENT_START_TIME
```

`actual_restoration_minutes` is kept as the backward-compatible evaluation column and, for ReportPO outputs, is an alias of `reportpo_first_restore_minutes`.

Field semantics confirmed from field crew input:

- `EVENT_START_TIME` is an operational start timestamp. It may align with the outage received time or the time the repair crew leaves the office.
- `FIRST_RESTORE_TIME` means power has been restored for the first time, so it is the current provisional restoration truth for ReportPO-based shadow evaluation.
- `EVENT_ETR_TIME` is the ETR time that was sent or adjusted; it is not an actual restoration target.
- `EVENT_END_TIME` is when the repair crew returns to the office or the event is administratively closed; do not use it as customer-facing restoration truth.

When AIS provides site-level outage/restoration timestamps, AIS truth should supersede ReportPO event-level truth for customer-facing model evaluation.

```powershell
python -m ais_etr reportpo-etr-refresh
python -m ais_etr reportpo-etr-alias-template
```

Equivalent step-by-step commands:

```powershell
python -m ais_etr reportpo-etr-fetch --template reportpo_querydata_alltabs.json --output runtime/reportpo_etr_querydata_latest.json --count 30000 --pages 3
python -m ais_etr reportpo-etr-import --source runtime/reportpo_etr_querydata_latest.json --output runtime/reportpo_etr_latest.csv
python -m ais_etr reportpo-etr-match-truth --reportpo runtime/reportpo_etr_latest.csv --output runtime/shadow_truth_mapping_reportpo.csv --audit runtime/reportpo_etr_truth_match_audit.csv --alias-file runtime/reportpo_device_aliases.csv --candidates-output runtime/reportpo_etr_no_match_candidates.csv --overwrite
python -m ais_etr reportpo-etr-alias-template --candidates runtime/reportpo_etr_no_match_candidates.csv --output runtime/reportpo_device_aliases.csv
python -m ais_etr shadow-report --truth-mapping runtime/shadow_truth_mapping_reportpo.csv --output runtime/shadow_evaluation_reportpo.csv
```

The matcher auto-fills truth only for exact device/time matches and approved device aliases. Feeder-only candidates are written for review and are not used as confident truth until an alias row is manually set to `approved`.

## AIS Site Truth Import

When AIS provides site/meter outage and restoration timestamps, prepare or validate the file with:

```powershell
python -m ais_etr ais-truth-template --output runtime/ais_truth_template.csv
python -m ais_etr ais-truth-import --source path\to\ais_truth.csv --output runtime/ais_truth_latest.csv --rejects-output runtime/ais_truth_rejects.csv
python -m ais_etr ais-truth-match-shadow --ais-truth runtime/ais_truth_latest.csv --output runtime/shadow_truth_mapping_ais.csv --audit runtime/ais_truth_shadow_match_audit.csv
python -m ais_etr shadow-report --truth-mapping runtime/shadow_truth_mapping_ais.csv --output runtime/shadow_evaluation_ais.csv
```

Template/input columns:

```text
site_id,peano,outage_start_time,power_restore_time,event_number,device_id,feeder,source,notes
```

Canonical output adds:

```text
actual_restoration_minutes = power_restore_time - outage_start_time
truth_source               = ais_site_power_status
truth_target               = ais_site_actual_restoration_minutes
truth_definition           = AIS_POWER_RESTORE_TIME - AIS_POWER_OUTAGE_TIME
truth_quality              = OK|REVIEW_SHORT|MISSING_*|INVALID_*
```

Rows with missing asset id, missing times, negative duration, or duration above 24 hours are written to the rejects file. `REVIEW_SHORT` rows stay in the canonical output but should be checked before model evaluation.

AIS truth matching precedence for shadow evaluation:

```text
event_number -> affected PEANO from shadow payload -> device+time -> feeder+time audit-only
```

If multiple AIS sites match the same Webex event, the default event-level truth uses the maximum AIS restoration duration. This is conservative for customer-facing evaluation because the slowest affected AIS site matters most. Feeder-only matches are written to audit but are not auto-filled unless `--allow-feeder` is explicitly set.

## Runtime Tables

- `webex_messages`
- `outage_events`
- `customer_assets`
- `predictions`
- `notifications`
- `model_runs`

## Safety Defaults

- Notification mode defaults to `shadow`.
- The notifier refuses non-shadow payloads.
- `NO_METER` registry rows remain in the repair backlog and are excluded from confident matching.
- If no mock webhook URL is configured, notification payloads are stored with `SKIPPED_NO_ENDPOINT`.
- `poll-loop` supports `--iterations` so pilot dry-runs can be bounded.

## Webex Auth Note

For bot-token polling, set `WEBEX_AUTH_MODE=bot`, `WEBEX_BOT_TOKEN`, and `WEBEX_ROOM_ID`. For group spaces, Webex bots can only access messages where they are mentioned. Keep `WEBEX_REQUIRE_MENTION=true` unless the room design guarantees direct bot messages.

## Parser Sample Corpus

`data/webex_shadow_samples.jsonl` contains representative outage messages and expected parser fields. Run `python -m ais_etr sample-eval` whenever Webex wording changes.
