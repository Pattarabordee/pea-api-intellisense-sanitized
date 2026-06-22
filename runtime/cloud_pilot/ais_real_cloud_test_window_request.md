# AIS Cloud Pilot Test Window Request

ส่งให้ AIS ผ่านช่องทางทำงานปกติได้ แต่ `X-API-Key` ส่งแยกผ่าน secure direct channel เท่านั้น.

## Request

- URL: `https://pea-api-intellisense-api.onrender.com/api/v1/ais/outage-verifications`
- Method: `POST`
- Headers:
  - `Content-Type: application/json`
  - `X-API-Key: <cloud pilot key via secure channel only>`
- Mode: `shadow/pilot only`
- Production send: `blocked`

## Test Window Ask

1. Send one valid request.
2. Send the same `request_id` again to test duplicate/idempotency.
3. Reply with only `request_id`, sent time, and HTTP status observed.

## Sample Body

```json
{
  "request_id": "AIS-CLOUD-PILOT-YYYYMMDD-0001",
  "meter_no": "REDACTED-METER-0000",
  "timestamp": "2026-06-22T10:00:00+07:00",
  "province": "Sakon Nakhon",
  "district": "Phang Khon",
  "subdistrict": "Demo",
  "alarm_type": "AC_MAIN_FAIL",
  "main_cause": "AC main failed",
  "subcause": "PEA no back up"
}
```

## Expected Result

- Valid request: `202 Accepted`
- Duplicate `request_id`: duplicate-safe response; no production resend
- Missing/invalid key: `401`
- Bad JSON/timestamp: safe `400`

Customer-facing Auto ETR is not live.
