# PEA AIS Meter-State API Contract v1

Status: canonical shadow contract. `production_send=blocked`.

## Endpoint

```http
POST https://pea-api-intellisense-api.onrender.com/api/v1/ais/outage-verifications
Content-Type: application/json
X-API-Key: <shared pilot key>
```

`GET /health` is public. Metrics, operator lists, request status, and truth intervals require the API key.

## Required Fields

| Field | Rule |
| --- | --- |
| `request_id` | Unique per request; reuse only when retrying the same request. |
| `meter_no` | Meter/service-point identity used by PEA's meter-state lifecycle. |
| `timestamp` | ISO 8601 event time. A missing offset is interpreted as Asia/Bangkok and flagged. |
| `event_type` or allowlisted structured signal | Explicit `OUTAGE`/`RESTORE` is preferred. Allowlisted `power_status`, `event_status`, or `status` values may be mapped. Exact `alarm_type=AC_MAIN_FAIL` maps to `OUTAGE`; exact `alarm_type=AC_MAIN_RESTORE` maps to `RESTORE` for prospective v2 requests. |

Optional evidence: `source_event_id`, `site_id`, `location_id`, area fields, alarm type, and cause fields. Optional identifiers are hashed before persistence and are not pairing keys.

Cause text cannot create model truth. An unknown or non-allowlisted status/alarm is accepted for audit as `REVIEW_EVENT_TYPE`. No RESTORE mapping is inferred from `mainCause` or `subcause`.

The authenticated operator list includes `semantic_capture_version=v2`, `semantic_mapping_version=alarm_mapping_v2`, and a sanitized `semantic_signals` object for newly captured rows. Signals contain only fixed event/status/alarm fields; unsafe or long categorical values are represented by a hash reference only.

Rows captured before v2 activation remain audit-only. They are never replayed or relabeled into model-ready truth.

For each new v2 OUTAGE that passes ledger validation, the cloud records a private research benchmark
`fixed_naive_60m_v1` with p50 = 60 minutes at request receipt time. This is a pre-registered naive baseline,
not a trained or promoted model. It is visible only through the authenticated operator response, is excluded
from callback/outbox payloads, and always remains `production_send=blocked`.

## Meter-State Rules

- First OUTAGE opens one interval for the meter.
- Repeated OUTAGE keeps the same interval open.
- RESTORE closes the single open interval.
- RESTORE without an open interval is `REVIEW_NO_OPEN_INTERVAL`.
- Multiple open intervals are quarantined as `REVIEW_MULTIPLE_OPEN_INTERVALS`.
- RESTORE must follow OUTAGE.
- Duration must be `>5` and `<=1440` minutes for `METER_STATE_MODEL_READY`.
- Legacy, strict-source-event, and preactivation v1 intervals remain audit-only.
- A v2 RESTORE can close only a v2 open interval with the same semantic mapping version.

## Examples

```json
{
  "request_id": "AIS-REQUEST-0001",
  "meter_no": "<meter number>",
  "timestamp": "2026-07-10T10:00:00+07:00",
  "event_type": "OUTAGE"
}
```

```json
{
  "request_id": "AIS-REQUEST-0002",
  "meter_no": "<same meter number>",
  "timestamp": "2026-07-10T11:15:00+07:00",
  "event_type": "RESTORE"
}
```

The response confirms capture only. It does not confirm an ETR, callback, or customer send.

## Passive Semantic Audit

Run the one-shot, GET-only audit after at least 100 requests or 7 observation days:

```powershell
python -m ais_etr ais-event-semantic-audit-once --base-url https://pea-api-intellisense-api.onrender.com
```

The audit writes aggregate evidence under `runtime/private/`. It never trains a model or sends a callback.

The restore contract becomes an activation candidate only when all conditions pass:

- at least 100 `semantic_capture_version=v1` requests, or a 7-day observation window;
- at least 20 valid same-meter `AC_MAIN_FAIL -> AC_MAIN_RESTORE` pairs;
- every candidate pair has duration `>5` and `<=1440` minutes;
- no semantic conflict or missing meter/time evidence.

The gate passed on sanitized aggregate evidence: 109 capture rows, 35 valid same-meter chronological pairs, no invalid pair, no missing identity/time, and no semantic conflict. Historical candidates remain `preactivation_pair_policy=audit_only`. Prospective requests use `semantic_capture_version=v2` and `semantic_mapping_version=alarm_mapping_v2`.

## Model Truth

The only customer-facing evaluation target is:

```text
ais_event_remaining_restoration_minutes = restore_at - prediction_created_at
```

If no prediction exists, use `request_received_at`. Interval duration (`restore_at - outage_at`) is control evidence only. Protection, topology, ReportPO, SFSD, WebEx, LINE, and telecom/GIS remain context-only.

MAE evaluation requires a numeric prediction snapshot created before RESTORE. Historical v1 rows and v2
rows captured before the research baseline activation remain truth/audit evidence only and cannot be scored
retroactively as if a prediction had existed.
