# PEA API Intellisense - Google Workspace Zero-Cost Pilot

สถานะ: **zero-cost cloud pilot / shadow mode**

แพ็กนี้ทำให้ AIS ยิง request เข้า Google Apps Script Web App ได้ โดยไม่ต้องเปิด laptop/PC และไม่ต้องเช่า Cloud ตอนนี้ ระบบจะเก็บ request/result ลง Google Sheets และให้ทีม Operation ดูย้อนหลังได้ทันที

> Guardrail: `mode = shadow`, `production_send = blocked`, ยังไม่ใช่ production Auto ETR

## สิ่งที่แพ็กนี้ทำได้

- รับ AIS outage verification request ผ่าน Apps Script Web App
- เก็บข้อมูลลง Google Sheets แบบ redacted: เก็บ meter เป็น `hash` + `last4`
- กัน `request_id` ซ้ำแบบ idempotency
- lookup meter hash กับ `topology_lookup`
- match device/feeder กับ `evidence_events`
- สร้างผลลัพธ์ decision เช่น `CONFIRMED_PEA_OUTAGE`, `UNCERTAIN_NEEDS_REVIEW`, `NO_PEA_EVIDENCE_FOUND`
- แสดง ETR เป็น `SHADOW_ONLY` เท่านั้น
- ให้ AIS/PEA lookup ผลด้วย `request_id`

## ข้อจำกัดสำคัญของ Apps Script

Apps Script Web App แบบ direct มีข้อจำกัดที่กระทบ API contract เดิม:

- อ่าน custom header เช่น `X-API-Key` ไม่ได้โดยตรง จึงใช้ `pilot_key` ใน query/body แทน
- ตั้ง HTTP status จริงเป็น `202` หรือ `401` เองไม่ได้เสถียรแบบ API gateway จึงใส่ logical status ใน JSON เช่น `"http_status": 202`
- Google ContentService มี redirect ไป `script.googleusercontent.com` ดังนั้นเวลาทดสอบด้วย `curl` ต้องใช้ `-L`
- เหมาะกับ pilot traffic ไม่เยอะ ไม่ใช่ production backend ระยะยาว

ถ้า AIS ต้องการ `X-API-Key` และ HTTP `202 Accepted` จริงแบบ strict ต้องกลับไปใช้ API gateway / Cloud Run / VM container ตอนมีทุน

## Files

| File | ใช้ทำอะไร |
| --- | --- |
| `Code.gs` | Apps Script Web App code |
| `appsscript.json` | Apps Script manifest |
| `pea_api_intellisense_google_workspace_pilot.xlsx` | Google Sheets template สำหรับ import |
| `test_request.json` | ตัวอย่าง request สำหรับทดสอบ |
| `sheet_schema.md` | อธิบาย tab/column |
| `setup_checklist.md` | ขั้นตอน deploy |

## Google Sheet Tabs

- `settings`: ตั้งค่า pilot เช่น `pilot_key_sha256`
- `inbound_requests`: request/result ทุกครั้งที่ AIS ยิงเข้ามา
- `topology_lookup`: meter hash -> feeder/protection devices
- `evidence_events`: event/device evidence แบบ sanitized
- `audit_log`: audit trail แบบอ่านง่าย

## AIS Test Endpoint Shape

Apps Script URL จะเป็นประมาณนี้:

```text
https://script.google.com/macros/s/<DEPLOYMENT_ID>/exec
```

Health check:

```text
GET <WEB_APP_URL>?health=1
```

POST request:

```text
POST <WEB_APP_URL>?pilot_key=<shared pilot key>
Content-Type: application/json
```

Body:

```json
{
  "request_id": "AIS-20260621-0001",
  "meter_no": "<REDACTED_METER_REF>",
  "timestamp": "2026-06-21T14:30:00+07:00",
  "province": "Sakon Nakhon",
  "district": "Phang Khon",
  "subdistrict": "Demo",
  "alarm_type": "AC_MAIN_FAIL",
  "main_cause": "Faulty AC main failed",
  "subcause": "PEA no back up"
}
```

Expected JSON response:

```json
{
  "api_version": "v1",
  "schema_version": "2026-06-21-google-workspace-pilot",
  "mode": "shadow",
  "status": "RECEIVED",
  "http_status": 202,
  "request_id": "AIS-20260621-0001",
  "duplicate": false,
  "callback_status": "CAPTURED_GOOGLE_SHEETS_ONLY",
  "production_send": "blocked"
}
```

Lookup:

```text
GET <WEB_APP_URL>?request_id=AIS-20260621-0001&pilot_key=<shared pilot key>
```

## PowerShell Test

```powershell
$url = "https://script.google.com/macros/s/<DEPLOYMENT_ID>/exec"
$key = Read-Host "pilot key"
$body = Get-Content -Raw ".\runtime\google_workspace_pilot\test_request.json"
Invoke-RestMethod -Method Post -Uri "$url?pilot_key=$key" -ContentType "application/json" -Body $body
```

ถ้าใช้ `curl`:

```bash
curl -L -X POST "$WEB_APP_URL?pilot_key=$PILOT_KEY" \
  -H "Content-Type: application/json" \
  --data @runtime/google_workspace_pilot/test_request.json
```

## Setup Summary

1. Import `pea_api_intellisense_google_workspace_pilot.xlsx` เป็น Google Sheets
2. เปิด Sheet > Extensions > Apps Script
3. วาง `Code.gs`
4. ตั้งค่า `pilot_key_sha256` ใน tab `settings`
5. Deploy > Web app > Execute as `Me` > Who has access `Anyone`
6. ส่ง Web App URL ให้ AIS พร้อมบอกว่า zero-cost pilot ใช้ `pilot_key` query/body แทน `X-API-Key`

## Security Notes

- อย่าใส่ API key จริงใน `Code.gs`
- อย่า share Google Sheet แบบ public
- อย่าใส่ verbatim WebEx text, room id, token, customer identity, full PEANO list ลงไฟล์ public
- ถ้าต้องเอา topology จริงขึ้น Sheet ให้ใช้ `meter_hash` แทน meter เต็ม
- `production_send` ต้องอยู่ที่ `blocked`

## Recommended Executive Wording

> This is a zero-CAPEX Google Workspace pilot that removes dependency on a local laptop. It is suitable for shadow-mode validation and executive demo, while production-grade API gateway, monitoring, backup, and strict auth remain pending funding.
