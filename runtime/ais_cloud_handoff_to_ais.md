# AIS Cloud Shadow API Handoff

Status: `cloud shadow pilot`  
Mode: `shadow`  
Production send: `blocked`

## Endpoint

```http
POST https://pea-api-intellisense-api.onrender.com/api/v1/ais/outage-verifications
```

## Headers

```http
Content-Type: application/json
X-API-Key: <cloud pilot key shared through secure channel only>
```

Do not paste the key in group chat, slides, GitHub, or public docs.

## Minimal Request Body

```json
{
  "request_id": "AIS-20260622-0001",
  "meter_no": "REDACTED-METER-0000",
  "timestamp": "2026-06-22T09:00:00+07:00",
  "province": "Sakon Nakhon",
  "district": "Phang Khon",
  "subdistrict": "Demo",
  "alarm_type": "AC_MAIN_FAIL"
}
```

Use ISO 8601 timestamp with timezone. Preferred timezone is `+07:00`.

## Expected Valid Response

```json
{
  "mode": "shadow",
  "status": "RECEIVED",
  "http_status": 202,
  "request_id": "AIS-20260622-0001",
  "duplicate": false,
  "callback_status": "CAPTURED_NO_CALLBACK_URL",
  "production_send": "blocked"
}
```

`202 Accepted` means PEA received and stored the request. It does not mean customer-facing ETR is approved.

## Please Report Back After Test

After AIS sends a test request, please share only these three values with PEA:

- `request_id`
- sent time
- HTTP status seen by AIS, such as `202`, `400`, or `401`

Do not send the API key back in chat.

## Error Meaning

- `401`: endpoint reached, but `X-API-Key` is missing or wrong.
- `400`: JSON body or timestamp format is invalid.
- `429`: retry too fast; slow down and reuse the same `request_id`.
- duplicate `request_id`: safe idempotency path; PEA does not reprocess production send.

## Safety Note

This endpoint is for pilot/shadow traffic only. PEA captures the request, stores redacted evidence, and keeps `production_send = blocked` until the production gate and owner approval pass.
