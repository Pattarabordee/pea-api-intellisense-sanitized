# Data Sources And Runtime

## Canonical Data Sources

| Source | Purpose | Notes |
| --- | --- | --- |
| `upstream_result.xlsx` | AIS meter/protection registry | Main AIS asset map. Sheet `Upstream Trace`. |
| `runtime/no_meter_backlog.csv` | Repair queue | `NO_METER` rows excluded from confident customer impact matching. |
| `ETR_PKN_2024.xlsx`, `ETR_PKN_2025.xlsx`, `ETR_PKN_2026_6M.xlsx` | Historical restoration target and model training | Header row 3. Use actual restoration minutes, not historical ETR timestamp. |
| `Event_from_report52_PKN.xlsx` | Event context | Feeder, device, cause/weather, event report fields. |
| `gis_distance.csv` | GIS distance feature | Has `OK`, `NOT_FOUND`, and missing distance rows. Missingness must remain visible. |
| `data/webex_shadow_samples.jsonl` | Parser regression sample | 24 sample cases. Not enough alone for production wording coverage. |
| `runtime/ais_etr.sqlite` | Runtime state | Queryable local evidence for Webex, events, assets, predictions, notifications, model runs, inbound requests. |
| `runtime/model_quantiles.json` | Current baseline model artifact | Quantile baseline, gate fail. |
| `AC_MAIN_FAIL_add_field.xlsx` and related runtime outputs | AIS add-field truth candidate lane | Used for AIS-side outage/restore truth import and validation. |
| `ReportPO` exports/runtime files | PEA operational context | Context/quarantine unless owner-approved; not customer-facing AIS truth. |
| `SFSF/SFSD` runtime outputs | PEA context/lifecycle candidates | Context/quarantine unless owner-approved. |

## SQLite Tables

| Table | Current rows | Use |
| --- | ---: | --- |
| `webex_messages` | 500 | Webex source storage and idempotency. |
| `outage_events` | 500 | Current parsed event state. |
| `customer_assets` | 390 | AIS registry loaded from upstream trace. |
| `predictions` | 2,500 | Append-style prediction history. |
| `notifications` | 2,510 | Shadow notification/send/capture history. |
| `model_runs` | 1 | Model training metadata. |
| `ais_inbound_requests` | 35 | AIS inbound request evidence. |
| `ais_inbound_callbacks` | 37 | AIS inbound callback/capture evidence. |

## AIS Registry Snapshot

| Metric | Count |
| --- | ---: |
| Total assets | 390 |
| Trace status `OK` | 271 |
| Trace status `NO_METER` | 119 |
| Confidence eligible | 271 |
| With feeder | 271 |
| With transformer id | 390 |
| With recloser | 237 |
| With switch | 271 |
| With CB | 271 |

Interpretation:

- `OK` rows are eligible for confident match.
- `NO_METER` rows are repair backlog, not confident customer impact.
- Feeder fallback is low-confidence and should stay shadow/review-only.

## Webex And Event Snapshot

| Metric | Current value |
| --- | --- |
| Webex message created range | 2026-03-22 to 2026-06-17 |
| Webex processed rows | 500 / 500 |
| Distinct room count | 1, redacted |
| Event time source | 500 `operation_row` |
| Parsed event number count | 0 |
| Event time range | 2024-07-11 to 2026-06-17 |

Device mix:

| Device type | Events |
| --- | ---: |
| Recloser | 372 |
| CB | 108 |
| Switch | 18 |
| Unknown | 2 |

Webex device state:

| Class | Events |
| --- | ---: |
| `momentary_le_1m` | 344 |
| `sustained_candidate` | 156 |

## Prediction And Notification Snapshot

Predictions:

| Metric | Value |
| --- | ---: |
| Prediction rows | 2,500 |
| Distinct prediction event refs | 1,000 |
| Rows joining current `outage_events` | 1,500 |
| Rows not joining current `outage_events` | 1,000 |
| q50 average | 28.14 min |
| q50 min/max | 0.08 / 74.02 min |
| affected_count avg | 5.69 |
| affected_count min/max | 0 / 14 |

Risk level counts:

| Risk | Rows |
| --- | ---: |
| MEDIUM | 1,140 |
| HIGH | 942 |
| LOW | 418 |

Notifications:

| Metric | Value |
| --- | ---: |
| Notification rows | 2,510 |
| Mode `shadow` | 2,510 |
| `REPLAY_CAPTURED` | 2,450 |
| `SENT` | 50 |
| `ERROR` | 10 |
| Rows joining current `outage_events` | 1,500 |
| Rows not joining current `outage_events` | 1,010 |

Shadow policy on current payloads:

| Gate | Rows |
| --- | ---: |
| `review_only` | 377 |
| `shadow_etr_candidate` | 123 |

Top reasons:

| Reason | Rows |
| --- | ---: |
| `momentary_webex_operation_requires_active_ais_outage_confirmation` | 330 |
| `confident_protection_match_with_sustained_like_webex_state` | 123 |
| `no_confident_ais_customer_match` | 47 |

## AIS Inbound Snapshot

| Metric | Value |
| --- | ---: |
| Total inbound requests | 35 |
| Smoke/demo requests | 31 |
| Non-smoke requests | 4 |
| Request callback status `CAPTURED_NO_CALLBACK_URL` | 35 |
| Callback rows `SKIPPED_DUPLICATE` | 2 |
| Response status `RECEIVED` | 35 |
| Production send `blocked` in parsed responses | 24 |

Separate cloud status report says:

- Cloud API health: `ok`
- Cloud database: `ok`
- Cloud total requests: 5
- Cloud non-smoke requests: 0
- Cloud production send: `blocked`

So local inbound evidence and cloud evidence are different lanes. Do not merge them without checking source.

## Runtime Caveats

- `outage_events` has one current row per Webex message id, but `predictions` and `notifications` are append-style history. Old prediction/notification rows can point to event ids that were replaced by replay/reprocess.
- Parser sample performance does not prove production Webex wording coverage.
- ReportPO and SFSD may contain useful context, but are not AIS customer-facing truth unless owner-approved.
- Do not export raw SQLite, Webex raw text, room ids, PEANO lists, or customer identity to external review.

