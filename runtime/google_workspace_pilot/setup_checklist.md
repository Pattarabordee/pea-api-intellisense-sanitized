# Setup Checklist - Google Workspace Zero-Cost Pilot

## 1. Create / Import Sheet

ใช้ไฟล์:

```text
runtime/google_workspace_pilot/pea_api_intellisense_google_workspace_pilot.xlsx
```

Import เป็น Google Sheets แล้วตรวจว่ามี tab:

- `settings`
- `inbound_requests`
- `topology_lookup`
- `evidence_events`
- `audit_log`

## 2. Compute Pilot Key Hash

ห้ามวาง key จริงในไฟล์หรือ group chat

PowerShell:

```powershell
$key = Read-Host "Pilot key"
$bytes = [System.Text.Encoding]::UTF8.GetBytes($key)
$hash = [System.Security.Cryptography.SHA256]::Create().ComputeHash($bytes)
($hash | ForEach-Object { $_.ToString("x2") }) -join ""
```

นำ hash ที่ได้ไปใส่:

```text
settings!B2
```

โดย `settings!A2` ต้องเป็น:

```text
pilot_key_sha256
```

## 3. Add Apps Script

1. เปิด Google Sheet
2. Extensions > Apps Script
3. วางเนื้อหา `Code.gs`
4. Save
5. Run function `setupPilotSheets` 1 ครั้ง เพื่อ authorize

## 4. Deploy Web App

Deploy > New deployment > Web app

Recommended:

- Execute as: `Me`
- Who has access: `Anyone`

เหตุผล: AIS external system ต้องยิงเข้ามาได้โดยไม่ login Google

## 5. Test Health

```text
GET <WEB_APP_URL>?health=1
```

ต้องเห็น:

```json
{
  "mode": "shadow",
  "status": "OK",
  "production_send": "blocked"
}
```

## 6. Test POST

PowerShell:

```powershell
$url = "https://script.google.com/macros/s/<DEPLOYMENT_ID>/exec"
$key = Read-Host "Pilot key"
$body = Get-Content -Raw ".\runtime\google_workspace_pilot\test_request.json"
Invoke-RestMethod -Method Post -Uri "$url?pilot_key=$key" -ContentType "application/json" -Body $body
```

Expected JSON:

```json
{
  "mode": "shadow",
  "status": "RECEIVED",
  "http_status": 202,
  "production_send": "blocked"
}
```

Note: HTTP status จริงจาก Apps Script อาจเป็น `200`; ให้ดู `http_status` ใน JSON สำหรับ pilot นี้

## 7. Test Duplicate

ยิง request เดิมอีกครั้ง

Expected:

```json
{
  "duplicate": true,
  "callback_status": "SKIPPED_DUPLICATE"
}
```

## 8. Test Lookup

```text
GET <WEB_APP_URL>?request_id=AIS-20260621-GWS-0001&pilot_key=<shared pilot key>
```

Expected:

```json
{
  "mode": "shadow",
  "status": "COMPLETED",
  "production_send": "blocked"
}
```

## 9. What To Send AIS

ส่งแบบนี้:

```text
URL:
<WEB_APP_URL>

Method:
POST

Headers:
Content-Type: application/json

Auth for zero-cost Apps Script pilot:
Add ?pilot_key=<shared pilot key> to URL

Body:
Same AIS outage verification JSON as pilot contract

Important:
This Google Workspace pilot does not support X-API-Key header or real HTTP 202 status.
Use JSON field http_status=202 for pilot verification.
mode=shadow and production_send=blocked.
```

## 10. Do Not Claim

ห้าม claim ว่า:

- production-grade backend แล้ว
- Auto ETR พร้อมส่งลูกค้าจริงแล้ว
- security เทียบเท่า API gateway แล้ว

พูดได้ว่า:

```text
Zero-CAPEX cloud pilot is ready for shadow validation.
Production-grade API gateway and strict auth remain funding-dependent.
```
