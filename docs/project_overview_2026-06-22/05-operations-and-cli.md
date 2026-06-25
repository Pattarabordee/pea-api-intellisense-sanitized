# Operations And CLI

## CLI Entry Point

Use:

```powershell
python -m ais_etr <command>
```

Main command registry lives in `ais_etr/cli.py`.

## Core Setup And Checks

```powershell
python -m ais_etr validate-env
python -m ais_etr init-db
python -m ais_etr build-registry
python -m ais_etr train
python -m ais_etr sample-eval
python -m ais_etr summary
```

Current `validate-env` result:

- `ok: true`
- missing config: none
- Webex auth mode: `oauth`
- Webex token file exists
- mock webhook configured
- notification mode: `shadow`

## Webex Operations

Common commands:

```powershell
python -m ais_etr webex-auth
python -m ais_etr webex-refresh-token
python -m ais_etr webex-rooms --query outage
python -m ais_etr poll-once --max-messages 50
python -m ais_etr poll-loop --interval-seconds 60 --iterations 10 --max-messages 50
python -m ais_etr webex-export-history --max-messages 500 --output runtime/webex_history_export.jsonl --csv-output runtime/webex_history_export.csv
python -m ais_etr webex-replay-history --source runtime/webex_history_export.jsonl --audit-output runtime/webex_history_replay_audit.csv
```

Handling:

- Export defaults avoid room id, actor identity, and raw JSON unless explicitly requested.
- Replay records `REPLAY_CAPTURED` shadow notifications and does not call AIS.
- Parser should be re-evaluated after wording changes.

## Registry And Repair

```powershell
python -m ais_etr build-registry
python -m ais_etr export-backlog --output runtime/no_meter_backlog.csv
python -m ais_etr no-match-repair-candidates --output runtime/no_match_registry_repair_candidates.csv
python -m ais_etr trace-no-match-candidates --candidates runtime/no_match_registry_repair_candidates.csv --upstream upstream_result.xlsx
python -m ais_etr source-trace-no-match-candidates --candidates runtime/no_match_registry_repair_candidates.csv --upstream upstream_result.xlsx
```

Rules:

- `NO_METER` stays in repair backlog.
- Source trace outputs must stay redacted.
- Protection overrides require private review and approved status before applying.

## AIS Truth Operations

```powershell
python -m ais_etr ais-truth-template --output runtime/ais_truth_template.csv
python -m ais_etr ais-truth-import --source path\to\ais_truth.csv --output runtime/ais_truth_latest.csv --rejects-output runtime/ais_truth_rejects.csv
python -m ais_etr ais-truth-match-shadow --ais-truth runtime/ais_truth_latest.csv --output runtime/shadow_truth_mapping_ais.csv --audit runtime/ais_truth_shadow_match_audit.csv
python -m ais_etr shadow-report --truth-mapping runtime/shadow_truth_mapping_ais.csv --output runtime/shadow_evaluation_ais.csv
```

AIS Add Field lane:

```powershell
python -m ais_etr ais-add-field-truth-import
```

Guardrails:

- Reject missing ids/times, negative durations, and >24h durations.
- `REVIEW_SHORT` rows remain review-only.
- Do not treat short/momentary rows as green truth without review.

## ReportPO And PEA Context

```powershell
python -m ais_etr reportpo-etr-refresh
python -m ais_etr reportpo-feature-refresh
python -m ais_etr reportpo-lifecycle-refresh
python -m ais_etr reportpo-shared-key-discovery
python -m ais_etr reportpo-manual-bridge-candidates
```

Use ReportPO/SFSD outputs for:

- context,
- bridge candidates,
- owner questions,
- lifecycle/cause features after approval.

Do not use them as AIS customer-facing restoration truth by default.

## Readiness And Gate Reports

```powershell
python -m ais_etr readiness-report
python -m ais_etr notification-time-readiness
python -m ais_etr ais-only-readiness
python -m ais_etr shadow-send-eligibility
python -m ais_etr green-eligibility-report
python -m ais_etr production-gate-packet
python -m ais_etr production-approval-evidence-pack
python -m ais_etr mvp-daily-qa
python -m ais_etr production-readiness-gate
```

Current important outputs:

- `runtime/green_gate_tracker.md`
- `runtime/production_path_readiness_gate.md`
- `runtime/cloud_pilot/production_gate_owner_packet.md`
- `runtime/cloud_pilot/mvp_daily_qa_report.md`

## AIS Inbound Local API

```powershell
python -m ais_etr ais-inbound-demo-request --output runtime/ais_inbound_demo_request.json --peano <PEANO>
python -m ais_etr ais-inbound-verify-file --source runtime/ais_inbound_demo_request.json --no-callback-post
python -m ais_etr ais-inbound-api --host 127.0.0.1 --port 8090 --no-callback-post
python -m ais_etr ais-inbound-status
python -m ais_etr ais-inbound-readiness-gate
```

Operator meaning:

- API returns accepted/shadow response and persists evidence.
- Callback can be captured or dry-run.
- It does not enable Auto ETR production.

## Daily Operator Pattern

1. Run `validate-env` and `summary`.
2. Check latest runtime/cloud reports.
3. If new Webex/AIS data arrived, refresh relevant audit/report command.
4. Review green gate and owner queues.
5. Do not change production send mode unless gate packet and approvals explicitly pass.

