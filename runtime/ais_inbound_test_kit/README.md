# PEA AIS Outage Verification API Pilot Test Kit

This package is for AIS pilot connectivity testing.

The endpoint is ready for pilot API testing, but it is still **shadow mode only**.
Automatic production ETR sending is blocked.

## URLs

```text
POST https://<REDACTED_TUNNEL>/api/v1/ais/outage-verifications
GET  https://<REDACTED_TUNNEL>/health
GET  https://<REDACTED_TUNNEL>/api/v1/ais/outage-verifications/{request_id}
```

## Required Headers

```http
Content-Type: application/json
X-API-Key: <private pilot key provided by PEA>
bypass-tunnel-reminder: true
```

`bypass-tunnel-reminder` is only needed for this localtunnel pilot.

## Files In This Kit

| File | Purpose |
| --- | --- |
| `current_endpoint.txt` | Current pilot URL and required headers. |
| `sample_minimal_request.json` | Smallest valid request body. |
| `sample_full_request.json` | Recommended request body with alarm context. |
| `curl_examples.md` | cURL commands for health, POST, and status lookup. |
| `powershell_examples.ps1` | PowerShell commands for Windows testing. |
| `ais_inbound_openapi.json` | OpenAPI contract, if copied from the runtime contract pack. |
| `ais_inbound_openapi.yaml` | OpenAPI YAML contract, if copied from the runtime contract pack. |
| `ais_inbound_postman_collection.json` | Postman collection, if copied from the runtime contract pack. |
| `manifest.json` | Machine-readable package manifest. |

## Expected Flow

1. Call `GET /health`.
2. Send one `POST` request with a unique `request_id`.
3. PEA confirms the request was stored.
4. Call `GET /api/v1/ais/outage-verifications/{request_id}`.
5. Review the response fields with PEA before sending a batch.

## Important Response Rules

- HTTP `202` means PEA received and stored the request.
- `status = RECEIVED` means the request passed validation.
- `production_send = blocked` must remain present.
- `mode = shadow` must remain present.
- The API may return `NO_PEA_EVIDENCE_FOUND` if current WebEx/topology evidence is not available for that meter/time.
- Any ETR field is for shadow evaluation only.

## Common Errors

| HTTP | Meaning |
| --- | --- |
| `400` | Invalid JSON, missing field, bad timestamp, or invalid identifier. |
| `401` | Endpoint is reachable, but the pilot API key is missing or invalid. |
| `404` | Path or request_id was not found. |
| `413` | Request body is too large. |
| `415` | `Content-Type: application/json` is missing or wrong. |
| `429` | Too many pilot requests. Retry after the `Retry-After` header. |

## Security Notes

- This package does not contain the private pilot API key.
- Do not send the private key in group chat.
- Full meter numbers are not written into public reports; the API stores hash and last4 for audit.
- This local tunnel is acceptable for pilot connectivity testing, not final production hosting.
