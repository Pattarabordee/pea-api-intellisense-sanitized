# PEA AIS Outage Verification API Contract v1

Generated: `2026-06-20T07:03:14+00:00`

Status: **pilot / shadow mode**. This API accepts real AIS test requests, stores redacted evidence in the local pilot runtime, and lets AIS/PEA read the verification result by `request_id`. **Automatic production ETR sending is still blocked.**

## Endpoints

```http
GET  https://<REDACTED_TUNNEL>/health
GET  https://<REDACTED_TUNNEL>/api/v1/ais/outage-verifications
POST https://<REDACTED_TUNNEL>/api/v1/ais/outage-verifications
GET  https://<REDACTED_TUNNEL>/api/v1/ais/outage-verifications/{request_id}
```

## Headers

```http
Content-Type: application/json
X-API-Key: <shared pilot key>
bypass-tunnel-reminder: true
```

`bypass-tunnel-reminder` is only needed during the localtunnel pilot. Do not share the real pilot key in group chat.

## Request Body

Required:

| Field | Meaning |
| --- | --- |
| `request_id` | Unique AIS alarm/event id. Reuse the same value when retrying the same event. Max 128 characters. Use letters, numbers, dash, underscore, dot, colon, or at sign only. |
| `meter_no` | PEA meter number / PEANO for the AIS site. Max 64 characters. Do not include slash, space, or newline. |
| `timestamp` | AIS detected outage time. Include timezone when possible, for example `+07:00`. |

Recommended:

| Field | Meaning |
| --- | --- |
| `province`, `district`, `subdistrict` | AIS site area. |
| `alarm_type` | For example `AC_MAIN_FAIL`. |
| `main_cause`, `subcause` | Used to separate PEA no-backup, PEA activity, and AIS equipment/backup cases. |

Example:

```json
{
  "request_id": "AIS-20260620-0001",
  "meter_no": "REDACTED-METER-0000",
  "timestamp": "2026-06-20T00:35:00+07:00",
  "province": "Sakon Nakhon",
  "district": "<district>",
  "subdistrict": "<subdistrict>",
  "alarm_type": "AC_MAIN_FAIL",
  "main_cause": "Faulty AC main failed",
  "subcause": "PEA no back up"
}
```

## Immediate Response

When the request is valid and the pilot key passes, the API returns HTTP `202 Accepted`.

```json
{
  "api_version": "v1",
  "schema_version": "2026-06-20",
  "mode": "shadow",
  "status": "RECEIVED",
  "http_status": 202,
  "request_id": "AIS-20260620-0001",
  "duplicate": false,
  "callback_status": "CAPTURED_NO_CALLBACK_URL",
  "result_path": "/api/v1/ais/outage-verifications/AIS-20260620-0001",
  "production_send": "blocked",
  "received_at": "2026-06-20T01:00:00+00:00"
}
```

## Result Lookup

AIS/PEA can read the stored verification result by `request_id`:

```http
GET https://<REDACTED_TUNNEL>/api/v1/ais/outage-verifications/{request_id}
```

The result indicates whether PEA evidence currently supports a distribution-side outage, the confidence level, the evidence lane used, and whether any ETR output is still `SHADOW_ONLY`.

The lookup also returns `timestamp_quality`. If AIS sends a timestamp without a timezone, the API treats it as Asia/Bangkok time and flags `timezone_assumed_bangkok`. Very old or future timestamps are accepted for audit, but flagged as `REVIEW` so operators do not silently compare bad timing evidence.

## Decision Status

| Status | Meaning |
| --- | --- |
| `CONFIRMED_PEA_OUTAGE` | Current WebEx/topology evidence supports a PEA distribution-side outage. |
| `UNCERTAIN_NEEDS_REVIEW` | More operator review is needed before confirming. |
| `NO_PEA_EVIDENCE_FOUND` | Current pilot runtime does not find supporting PEA evidence yet. |
| `PLANNED_OR_PEA_ACTIVITY` | AIS indicates this is PEA activity/planned context. |
| `LIKELY_AIS_EQUIPMENT_OR_BACKUP` | AIS subcause points to AIS equipment/backup context. |
| `DUPLICATE_REQUEST` | The same `request_id` was already received. |

## Error Responses

All error responses use the same envelope:

```json
{
  "api_version": "v1",
  "schema_version": "2026-06-20",
  "mode": "shadow",
  "status": "ERROR",
  "error": {
    "code": "UNAUTHORIZED",
    "message": "X-API-Key or Authorization Bearer credential is required"
  },
  "production_send": "blocked",
  "generated_at": "2026-06-20T01:00:00+00:00"
}
```

Common HTTP status:

| HTTP | Meaning |
| --- | --- |
| `202` | Request accepted. |
| `400` | Invalid JSON, missing required field, or invalid timestamp. |
| `401` | Missing or invalid pilot key. |
| `404` | Path or `request_id` not found. |
| `413` | Request body exceeds the pilot limit. |
| `415` | `Content-Type` is not `application/json`. |
| `429` | Too many requests. Retry after the `Retry-After` header value. |

## Guardrails

- `mode` must remain `shadow`.
- `production_send` must remain `blocked`.
- Default pilot rate limit is `120` POST requests per minute per client.
- WebEx is used as trigger/device evidence, not restoration truth.
- AIS outage/restore timestamps remain the primary customer-facing truth source for ETR evaluation.
- Feeder-only matches are review/audit-only.
- Automatic customer ETR is blocked until the green subset passes the production gate.

## Files

- OpenAPI JSON: `runtime/ais_inbound_openapi.json`
- OpenAPI YAML: `runtime/ais_inbound_openapi.yaml`
- Postman collection: `runtime/ais_inbound_postman_collection.json`
- Demo request: `runtime/ais_inbound_demo_request.json`
