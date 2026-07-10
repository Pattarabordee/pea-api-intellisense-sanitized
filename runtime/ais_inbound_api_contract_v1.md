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
| `event_type` or allowlisted structured signal | Explicit `OUTAGE`/`RESTORE` is preferred. Allowlisted `power_status`, `event_status`, or `status` values may be mapped. The exact structured code `alarm_type=AC_MAIN_FAIL` maps to `OUTAGE`. |

Optional evidence: `source_event_id`, `site_id`, `location_id`, area fields, alarm type, and cause fields. Optional identifiers are hashed before persistence and are not pairing keys.

Cause text cannot create model truth. An unknown or non-allowlisted status/alarm is accepted for audit as `REVIEW_EVENT_TYPE`. No RESTORE mapping is inferred from `mainCause` or `subcause`.

Observed `alarm_type=AC_MAIN_RESTORE` is recorded as a restore mapping candidate only. It remains `REVIEW_EVENT_TYPE` until the passive observation and contract gate are completed.

The authenticated operator list includes `semantic_capture_version=v1` and a sanitized `semantic_signals` object for newly captured rows. The audit excludes rows without this version marker. Signals contain only fixed event/status/alarm fields; unsafe or long categorical values are represented by a hash reference only.

## Meter-State Rules

- First OUTAGE opens one interval for the meter.
- Repeated OUTAGE keeps the same interval open.
- RESTORE closes the single open interval.
- RESTORE without an open interval is `REVIEW_NO_OPEN_INTERVAL`.
- Multiple open intervals are quarantined as `REVIEW_MULTIPLE_OPEN_INTERVALS`.
- RESTORE must follow OUTAGE.
- Duration must be `>5` and `<=1440` minutes for `METER_STATE_MODEL_READY`.
- Legacy and strict-source-event intervals remain audit-only.

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

Before this gate passes, `AC_MAIN_RESTORE` remains `STATUS` with `REVIEW_EVENT_TYPE`. Historical candidate pairs use `preactivation_pair_policy=audit_only`; they are never replayed into model-ready truth. A later activation must use `semantic_mapping_version=alarm_mapping_v2` and applies prospectively only.

## Model Truth

The only customer-facing evaluation target is:

```text
ais_event_remaining_restoration_minutes = restore_at - prediction_created_at
```

If no prediction exists, use `request_received_at`. Interval duration (`restore_at - outage_at`) is control evidence only. Protection, topology, ReportPO, SFSD, WebEx, LINE, and telecom/GIS remain context-only.
