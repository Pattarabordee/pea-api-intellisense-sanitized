# cURL Examples

Replace `<private pilot key provided by PEA>` with the private key shared outside this package.

## Health Check

```bash
curl -i \
  -H "bypass-tunnel-reminder: true" \
  "https://<REDACTED_TUNNEL>/health"
```

## Send One Test Request

```bash
curl -i -X POST \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <private pilot key provided by PEA>" \
  -H "bypass-tunnel-reminder: true" \
  --data '{
  "request_id": "AIS-TEST-0001",
  "meter_no": "REDACTED-METER-0000",
  "timestamp": "2026-06-20T00:35:00+07:00",
  "province": "Sakon Nakhon",
  "district": "<district>",
  "subdistrict": "<subdistrict>"
}' \
  "https://<REDACTED_TUNNEL>/api/v1/ais/outage-verifications"
```

Expected result: HTTP `202` with `status = RECEIVED`.

## Read Stored Result

```bash
curl -i \
  -H "X-API-Key: <private pilot key provided by PEA>" \
  -H "bypass-tunnel-reminder: true" \
  "https://<REDACTED_TUNNEL>/api/v1/ais/outage-verifications/AIS-TEST-0001"
```

## Authentication Check

If this returns HTTP `401`, the endpoint is reachable and authentication is being enforced.

```bash
curl -i -X POST \
  -H "Content-Type: application/json" \
  -H "bypass-tunnel-reminder: true" \
  --data '{"request_id":"AIS-AUTH-CHECK","meter_no":"TEST","timestamp":"2026-06-20T00:35:00+07:00"}' \
  "https://<REDACTED_TUNNEL>/api/v1/ais/outage-verifications"
```
