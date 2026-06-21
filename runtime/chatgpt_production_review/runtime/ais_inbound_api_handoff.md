# AIS -> PEA Outage Verification API: Pilot Handoff

Current status: the endpoint is ready for AIS testing. It is still **shadow mode only** and does not send automatic production ETR.

## Test URLs

```text
POST https://<REDACTED_TUNNEL>/api/v1/ais/outage-verifications
GET  https://<REDACTED_TUNNEL>/health
GET  https://<REDACTED_TUNNEL>/api/v1/ais/outage-verifications/{request_id}
```

Use `POST` to send one outage alarm/event. Use `GET .../{request_id}` to read the stored verification result for the same request.

## Headers

```http
Content-Type: application/json
X-API-Key: <private pilot key provided by PEA>
bypass-tunnel-reminder: true
```

`bypass-tunnel-reminder` is only needed for this localtunnel pilot to bypass the tunnel warning page.

## Minimal Body

```json
{
  "request_id": "AIS-TEST-0001",
  "meter_no": "<REDACTED_METER_REF>",
  "timestamp": "2026-06-20T00:35:00+07:00",
  "province": "Sakon Nakhon",
  "district": "<district>",
  "subdistrict": "<subdistrict>"
}
```

If AIS has alarm context, include it like this:

```json
{
  "request_id": "AIS-20260620-0001",
  "meter_no": "<REDACTED_METER_REF>",
  "timestamp": "2026-06-20T00:35:00+07:00",
  "province": "Sakon Nakhon",
  "district": "<district>",
  "subdistrict": "<subdistrict>",
  "alarm_type": "AC_MAIN_FAIL",
  "main_cause": "Faulty AC main failed",
  "subcause": "PEA no back up"
}
```

## Expected Response

If the request is valid, the API returns HTTP `202` and `status = RECEIVED`.

```json
{
  "mode": "shadow",
  "status": "RECEIVED",
  "http_status": 202,
  "request_id": "AIS-20260620-0001",
  "duplicate": false,
  "result_path": "/api/v1/ais/outage-verifications/AIS-20260620-0001",
  "production_send": "blocked"
}
```

Then read the result from:

```http
GET https://<REDACTED_TUNNEL>/api/v1/ais/outage-verifications/AIS-20260620-0001
```

## If There Is an Error

| Error | Meaning |
| --- | --- |
| `401` | The endpoint is reachable, but `X-API-Key` is missing or invalid. |
| `400` | Invalid JSON, missing required field, or invalid timestamp format. |
| `404` | The path or `request_id` was not found. |
| `415` | `Content-Type: application/json` is missing or wrong. |
| `429` | Too many pilot test requests. Retry after the `Retry-After` header value. |
| timeout | The tunnel or PEA pilot machine may be down. Ask PEA to check the endpoint. |

## Pilot Scope

- The API accepts requests and stores redacted runtime logs.
- The API supports status lookup by `request_id`.
- The pilot rate limit is 120 POST requests per minute per client.
- Any ETR output is still `SHADOW_ONLY`.
- `production_send` must remain `blocked`.
- Do not share the real pilot key in group chat.
