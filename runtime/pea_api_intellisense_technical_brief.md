# PEA API Intellisense - Technical Brief

> ใช้สำหรับส่งต่อให้ Dev, AI reviewer, หรือกรรมการที่อยากดูภาพเชิงเทคนิค  
> สถานะปัจจุบัน: `shadow mode` และ `production_send = blocked`  
> ระบบยังไม่ใช่ production auto ETR และยังไม่ใช่ direct relay/SCADA integration

## 1. Project Tree Structure

```text
D:\PEA Intellisense data
├─ ais_etr/
│  ├─ ais_inbound.py              # AIS inbound API: POST/GET/health, idempotency, evidence, response
│  ├─ db.py                       # SQLite schema + query helpers
│  ├─ registry.py                 # build AIS meter/topology registry from upstream_result.xlsx
│  ├─ matcher.py                  # protection matching logic: CB/Recloser/Switch/Transformer/Feeder
│  ├─ model.py                    # ETR prediction contract
│  ├─ parser.py                   # parse WebEx/device events
│  ├─ source_trace.py             # ArcGIS/TraceDownHV_LV audit/repair path
│  ├─ production_path.py          # sanitized export + production gate
│  └─ cli.py                      # all operator commands
├─ tests/
│  ├─ test_ais_inbound.py
│  ├─ test_production_path.py
│  ├─ test_registry.py
│  └─ ...
├─ runtime/
│  ├─ cloud_pilot/
│  ├─ ais_inbound_openapi.yaml
│  ├─ ais_inbound_postman_collection.json
│  ├─ PILOT_COMPLETE_README.md
│  └─ github_sanitized_source/
└─ upstream_result.xlsx           # source topology registry input
```

## 2. Data Flow

```text
AIS JSON
  -> POST /api/v1/ais/outage-verifications
  -> validate + normalize fields
  -> check request_id duplicate
  -> find meter in runtime.customer_assets
  -> load WebEx/outage event candidates + latest ETR prediction
  -> compare meter topology vs event device
  -> decide status/confidence
  -> return 202 Accepted immediately
  -> store request/callback evidence in SQLite
```

## 2.1 AIS Request JSON Fields

Required หลัก:

```json
{
  "request_id": "AIS-20260621-0001",
  "meter_no": "REDACTED-METER-0000",
  "timestamp": "2026-06-21T13:00:00+07:00",
  "province": "Sakon Nakhon",
  "district": "Phang Khon",
  "subdistrict": "Demo",
  "alarm_type": "AC_MAIN_FAIL",
  "main_cause": "Faulty AC main failed",
  "subcause": "PEA no back up"
}
```

ระบบรองรับ alias หลายชื่อ เช่น:

- `request_id`, `requestId`, `event_id`, `alarm_id`, `ticket_id`
- `meter_no`, `meter_id`, `meter`, `peano`, `PEANO`, `pea_no`
- `timestamp`, `detected_at`, `event_time`, `occurred_at`, `outage_start_time`
- `province`, `district`, `subdistrict`
- `alarm_type`, `main_cause`, `subcause`

ตำแหน่ง code:

- `ais_etr/ais_inbound.py`, function `_normalize_inbound_payload`

## 2.2 Meter/Topology Trace

Current inbound path ไม่ยิง live GIS ทุก request

ระบบใช้ topology registry ที่ build ไว้แล้วใน SQLite table `customer_assets`

แหล่งข้อมูลหลัก:

- `upstream_result.xlsx`
- sheet `Upstream Trace`
- load ด้วย `ais_etr/registry.py`
- save ลง SQLite table `customer_assets`

ข้อมูลที่เก็บต่อ meter:

- `peano`
- `feeder`
- `transformer_id`
- `transformer_peano`
- `recloser_ids`
- `switch_ids`
- `cb_ids`
- `trace_status`
- `confidence_eligible`

Logic match:

```text
ถ้า event device ตรงกับ CB       -> confidence 0.95
ถ้าตรงกับ Recloser              -> confidence 0.90
ถ้าตรงกับ Switch                -> confidence 0.86
ถ้าตรงกับ Transformer           -> confidence 0.72
ถ้าตรงแค่ Feeder                -> confidence 0.35, audit only
```

Live GIS/ArcGIS มีใช้ใน `source_trace.py` สำหรับ audit/repair mapping ไม่ใช่ request path หลักตอนนี้

`source_trace.py` ทำงานประมาณนี้:

1. Query PEA ArcGIS layer ด้วย `FACILITYID`
2. เลือก device feature ที่ feeder ตรงที่สุด
3. ใช้ geometry ของ device ไป run `TraceDownHV_LV`
4. สรุป downstream meter count / transformer count / AIS registry hits
5. รายงานเป็น evidence สำหรับซ่อม topology registry

## 2.3 Evidence Check

ระบบยังไม่ได้เช็ค SCADA/protection relay log ตรง ๆ แบบ production

Evidence ปัจจุบันคือ `WebEx + topology + prediction history` ใน SQLite:

- WebEx/device event ถูก parse เป็น `outage_events`
- model prediction อยู่ใน `predictions`
- inbound request อยู่ใน `ais_inbound_requests`
- callback/result อยู่ใน `ais_inbound_callbacks`

Query evidence ใช้ `_load_runtime_event_candidates()`:

1. ดึง `outage_events`
2. join latest `predictions`
3. เอา `device_id`, `feeder`, `event_time` มาเทียบกับ topology ของ meter
4. ต้องอยู่ใน time window ที่กำหนด
5. rank ตาม match level: `cb`, `recloser`, `switch`, `transformer`, `feeder`

ถ้า match ระดับ protection device เจอและอยู่ในช่วงเวลา ระบบตอบว่า `CONFIRMED_PEA_OUTAGE` ใน shadow response ได้

ถ้า match แค่ feeder ระบบให้เป็น `UNCERTAIN_NEEDS_REVIEW` เพราะ feeder-only เสี่ยง overmatch

## 3. Code Snippet

### 3.1 Decision Logic: ตอบ AIS ว่าเกี่ยวกับ PEA outage หรือไม่

```python
def _verification_status(
    asset: CustomerAsset | None,
    cause_lane: str,
    evidence: dict[str, Any],
) -> tuple[str, str, str]:
    if cause_lane == "pea_activity":
        return "PLANNED_OR_PEA_ACTIVITY", "MEDIUM", "ais_labeled_pea_activity"
    if cause_lane == "possibly_ais_equipment_or_backup":
        return "LIKELY_AIS_EQUIPMENT_OR_BACKUP", "LOW", "ais_subcause_points_to_non_pea_equipment_or_backup"
    if asset is None:
        return "NO_PEA_EVIDENCE_FOUND", "LOW", "meter_not_found_in_runtime_registry"
    if not asset.confidence_eligible:
        return "UNCERTAIN_NEEDS_REVIEW", "LOW", "meter_mapping_not_confidence_eligible"
    if evidence.get("match_found") and evidence.get("match_level") in CONFIDENT_LEVELS:
        return "CONFIRMED_PEA_OUTAGE", "HIGH", "confident_meter_to_protection_and_webex_match"
    if evidence.get("match_found") and evidence.get("match_level") == "feeder":
        return "UNCERTAIN_NEEDS_REVIEW", "MEDIUM", "feeder_match_is_audit_only"
    return "UNCERTAIN_NEEDS_REVIEW", "MEDIUM", "meter_in_registry_but_no_recent_webex_match"
```

Source:

- `ais_etr/ais_inbound.py`
- function `_verification_status`

### 3.2 Idempotency: ป้องกัน request_id เดียวกันประมวลผลซ้ำ

```python
duplicate = _request_exists(db, request["request_id"])
if duplicate:
    accepted = _accepted_response(request, callback_status="SKIPPED_DUPLICATE", duplicate=True)
    callback_payload = _build_duplicate_callback(request)
    callback_record = NotificationRecord(payload=callback_payload, status="SKIPPED_DUPLICATE")
    _append_jsonl(callbacks_output, _redacted_callback_log(callback_payload, callback_record, callback_url))
    _persist_callback(db.path, request["request_id"], callback_url, callback_payload, callback_record)
    return AisInboundResult(request["request_id"], accepted, callback_payload, callback_record, duplicate=True)
```

Source:

- `ais_etr/ais_inbound.py`
- function `process_ais_inbound_request`

## 4. Database Tables ที่เกี่ยวข้อง

### `customer_assets`

เก็บ mapping meter -> topology path

```text
peano
customer
feeder
meter_location
transformer_id
transformer_peano
recloser_ids
switch_ids
cb_ids
trace_status
confidence_eligible
raw_json
updated_at
```

### `outage_events`

เก็บ event ที่ parse จาก WebEx/device evidence

```text
event_id
webex_message_id
event_time
device_type
device_id
feeder
district
site
```

### `predictions`

เก็บ ETR prediction ต่อ event

```text
event_id
model_version
etr_minutes_p50
q10
q90
risk_level
match_confidence
affected_count
```

### `ais_inbound_requests`

เก็บ inbound request แบบ redacted

```text
request_id
received_at
peano_hash
peano_last4
detected_at
province
district
subdistrict
request_json
response_json
callback_status
```

### `ais_inbound_callbacks`

เก็บ callback/result evidence

```text
request_id
callback_url
mode
payload_json
status
status_code
response_text
sent_at
```

## 5. Important Caveat

ตอนนี้ระบบทำได้:

- รับ AIS API request
- normalize/validate payload
- กัน duplicate `request_id`
- trace meter จาก runtime topology registry
- เทียบกับ WebEx/topology evidence
- คืน `202 Accepted`
- เก็บ durable evidence ใน SQLite
- สร้าง shadow response พร้อม status/confidence/ETR lane

ตอนนี้ระบบยังไม่ได้ทำ:

- ยังไม่ production live
- ยังไม่ direct SCADA/protection relay log integration
- ยังไม่ส่ง customer-facing ETR อัตโนมัติ
- ยังไม่เปิด production send

Guardrail ปัจจุบัน:

```text
mode = shadow
production_send = blocked
```

